"""Training pipeline: load -> validate -> compare models -> evaluate -> select -> save.

Run from the project root:
    python -m backend.ml.train_model

Replaces the original train_model.py. Differences:
  * Several models are compared, not one.
  * Evaluation uses cross-validation. The old 80/20 split tested on only
    2 rows of a 10-row dataset, which cannot give a meaningful score.
  * A sanity check rejects models whose predictions go DOWN when an input
    such as attendance goes UP. On small, highly correlated data an
    unregularised linear model can fit the data exactly with nonsensical
    signs, and explanations built on it would mislead students.
  * The saved bundle carries feature names, metrics, training ranges,
    timestamp and library versions, so nothing is hard-coded elsewhere.
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.base import clone
from sklearn.dummy import DummyRegressor
from sklearn.ensemble import GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, LeaveOneOut, cross_val_predict, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from backend.config import DATASET_PATH, FEATURE_NAMES, METADATA_PATH, MODEL_DIR, MODEL_PATH, TARGET
from backend.utils.validation import read_csv_safely, validate_dataframe

SMALL_DATA_ROWS = 30          # below this, use leave-one-out CV
HOLDOUT_MIN_ROWS = 40         # from this size, 20% is held out as a test set the model never sees
RECOMMENDED_ROWS = 100        # below this, results are flagged as not reliable
MONOTONIC_TOLERANCE = 0.5     # score points a prediction may dip before failing the check
RANDOM_STATE = 42


def candidate_models() -> dict:
    """Every model is a Pipeline so preprocessing is saved with it."""
    return {
        "Baseline (predict the mean)": Pipeline([("model", DummyRegressor())]),
        "Linear Regression": Pipeline([("scale", StandardScaler()), ("model", LinearRegression())]),
        "Ridge Regression": Pipeline([("scale", StandardScaler()), ("model", Ridge(alpha=1.0))]),
        "Random Forest": Pipeline([("model", RandomForestRegressor(n_estimators=300, random_state=RANDOM_STATE))]),
        "Gradient Boosting": Pipeline([("model", GradientBoostingRegressor(random_state=RANDOM_STATE))]),
    }


def load_training_data(path=DATASET_PATH) -> tuple[pd.DataFrame, list[str]]:
    df, err = read_csv_safely(path)
    if err:
        raise ValueError(err)
    rep = validate_dataframe(df, require_target=True)
    if not rep.ok:
        raise ValueError("Training data is invalid: " + " ".join(rep.errors))
    return rep.clean[FEATURE_NAMES + [TARGET]], rep.warnings


def monotonic_check(model, X: pd.DataFrame) -> dict:
    """For each feature, sweep it across its observed range for every row and
    record the largest decrease in prediction. Domain expectation: raising
    attendance, marks or study time should never lower the predicted score."""
    worst = {}
    for f in FEATURE_NAMES:
        grid = np.linspace(X[f].min(), X[f].max(), 12)
        drops = []
        for _, row in X.iterrows():
            sweep = pd.DataFrame([row.values] * len(grid), columns=FEATURE_NAMES)
            sweep[f] = grid
            p = model.predict(sweep)
            drops.append(float(np.max(np.maximum.accumulate(p) - p)))
        worst[f] = round(max(drops), 3)
    return {"passed": all(v <= MONOTONIC_TOLERANCE for v in worst.values()), "worst_drop": worst}


def evaluate(df: pd.DataFrame) -> tuple[pd.DataFrame, dict, str]:
    X, y = df[FEATURE_NAMES], df[TARGET]
    n = len(df)
    if n < 5:
        raise ValueError(f"At least 5 rows are needed to train and evaluate; found {n}.")
    if n < SMALL_DATA_ROWS:
        cv, scheme = LeaveOneOut(), f"Leave-one-out cross-validation ({n} folds)"
    else:
        cv, scheme = KFold(5, shuffle=True, random_state=RANDOM_STATE), "5-fold cross-validation"

    rows, fitted = [], {}
    for name, model in candidate_models().items():
        pred = cross_val_predict(model, X, y, cv=cv)
        full = clone(model).fit(X, y)
        mono = monotonic_check(full, X) if not name.startswith("Baseline") else {"passed": True, "worst_drop": {}}
        rows.append({
            "Model": name,
            "R2": r2_score(y, pred),
            "MAE": mean_absolute_error(y, pred),
            "RMSE": float(np.sqrt(mean_squared_error(y, pred))),
            "Sanity check": "Pass" if mono["passed"] else "Fail",
            "Worst drop": max(mono["worst_drop"].values()) if mono["worst_drop"] else 0.0,
        })
        # half-width of an ~80% prediction interval, from HELD-OUT residuals only
        fitted[name] = (full, mono, float(np.quantile(np.abs(np.asarray(y) - pred), 0.8)))
    return pd.DataFrame(rows), fitted, scheme


def select_model(results: pd.DataFrame) -> tuple[str, str]:
    real = results[~results["Model"].str.startswith("Baseline")]
    passing = real[real["Sanity check"] == "Pass"]
    pool = passing if not passing.empty else real
    best = pool.sort_values("RMSE").iloc[0]["Model"]
    if passing.empty:
        reason = (f"No model passed the sanity check; {best} has the lowest cross-validated RMSE. "
                  "Treat explanations with extra caution.")
    else:
        failed = real[real["Sanity check"] == "Fail"]["Model"].tolist()
        reason = f"{best} has the lowest cross-validated RMSE among models that passed the sanity check."
        if failed:
            reason += (" Excluded: " + ", ".join(failed) + " (prediction falls when an input rises, "
                       "a sign of overfitting to correlated features).")
    return best, reason


def model_details(pipeline) -> dict:
    """Human-readable parameters for linear models (per original unit)."""
    est = pipeline.named_steps["model"]
    if not hasattr(est, "coef_"):
        return {}
    coef = np.asarray(est.coef_, dtype=float)
    intercept = float(est.intercept_)
    if "scale" in pipeline.named_steps:
        sc = pipeline.named_steps["scale"]
        coef = coef / sc.scale_
        intercept = intercept - float(np.sum(coef * sc.mean_))
    return {"coefficients": dict(zip(FEATURE_NAMES, map(float, coef))), "intercept": intercept}


def train(path=DATASET_PATH, save: bool = True, data: pd.DataFrame | None = None,
          data_sources: dict | None = None) -> dict:
    """Train and evaluate. `data` (already validated, de-duplicated) overrides the CSV at `path`.

    Evaluation never sees its own training rows: model comparison uses cross-validation, and from
    HOLDOUT_MIN_ROWS rows a 20% test set is split off first and scored only once, by the chosen model."""
    if data is None:
        df, warnings = load_training_data(path)
    else:
        df, warnings = data[FEATURE_NAMES + [TARGET]].reset_index(drop=True), []
    holdout = None
    if len(df) >= HOLDOUT_MIN_ROWS:
        train_df, test_df = train_test_split(df, test_size=0.2, random_state=RANDOM_STATE)
        results, fitted, scheme = evaluate(train_df)
        best, reason = select_model(results)
        on_train = fitted[best][0]
        yt, pt = test_df[TARGET].to_numpy(), on_train.predict(test_df[FEATURE_NAMES])
        base = np.full_like(yt, train_df[TARGET].mean(), dtype=float)
        holdout = {"rows": int(len(test_df)), "MAE": float(mean_absolute_error(yt, pt)),
                   "RMSE": float(np.sqrt(mean_squared_error(yt, pt))), "R2": float(r2_score(yt, pt)),
                   "baseline_MAE": float(mean_absolute_error(yt, base)), "train_rows": int(len(train_df))}
        scheme += f" on {len(train_df)} training rows; final check on a separate {len(test_df)}-row test set"
        pipeline = clone(candidate_models()[best]).fit(df[FEATURE_NAMES], df[TARGET])   # deploy on all rows
        mono = monotonic_check(pipeline, df[FEATURE_NAMES]) if not best.startswith("Baseline") else fitted[best][1]
        p80 = fitted[best][2]
    else:
        results, fitted, scheme = evaluate(df)
        best, reason = select_model(results)
        pipeline, mono, p80 = fitted[best]
    X = df[FEATURE_NAMES]

    n = len(df)
    limitations = []
    if SMALL_DATA_ROWS <= n < RECOMMENDED_ROWS:
        limitations.append(
            f"Only {n} training rows: at least {RECOMMENDED_ROWS} real records with final scores are recommended "
            "before relying on these predictions.")
    if holdout is None:
        limitations.append(
            f"No separate test set: with fewer than {HOLDOUT_MIN_ROWS} rows every row is needed for "
            "cross-validation, so there is no final unseen check.")
    if n < SMALL_DATA_ROWS:
        limitations.append(
            f"The dataset has only {n} rows. It is suitable for demonstrating the prototype but is "
            "insufficient for strong real-world generalisation. Metrics below come from very few "
            "held-out predictions and will change substantially with more data.")
    min_corr = float(df.corr().values[np.triu_indices(df.shape[1], 1)].min())
    if min_corr > 0.9:
        limitations.append(
            f"All columns are strongly correlated with each other (lowest pairwise correlation "
            f"{min_corr:.2f}). The model cannot reliably separate the effect of one factor from "
            "another, so per-factor explanations show association, not cause.")

    bundle = {
        "pipeline": pipeline,
        "model_name": best,
        "selection_reason": reason,
        "feature_names": FEATURE_NAMES,
        "target": TARGET,
        "metrics": results.set_index("Model").loc[best, ["R2", "MAE", "RMSE"]].astype(float).to_dict(),
        "cv_abs_residual_p80": p80,
        "holdout": holdout,
        "data_sources": data_sources or {"student_performance.csv": n},
        "dataset_sha256": hashlib.sha256(open(path, "rb").read()).hexdigest() if hasattr(path, "__fspath__") or isinstance(path, str) else None,
        "comparison": results.to_dict(orient="records"),
        "cv_scheme": scheme,
        "monotonic_check": mono,
        "training_rows": n,
        "training_ranges": {f: [float(X[f].min()), float(X[f].max())] for f in FEATURE_NAMES},
        "background": X.to_dict(orient="list"),     # used by the explainer
        "target_values": df[TARGET].astype(float).tolist(),
        "details": model_details(pipeline),
        "limitations": limitations,
        "data_warnings": warnings,
        "trained_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "sklearn_version": sklearn.__version__,
        "dataset_path": str(path),
    }
    if save:
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        joblib.dump(bundle, MODEL_PATH)
        meta = {k: v for k, v in bundle.items() if k not in ("pipeline", "background", "target_values")}
        METADATA_PATH.write_text(json.dumps(meta, indent=2, default=str))
    return bundle


def main():
    try:
        b = train()
    except ValueError as e:
        print("Training failed:", e)
        sys.exit(1)
    print(f"Evaluation: {b['cv_scheme']} on {b['training_rows']} rows\n")
    print(pd.DataFrame(b["comparison"]).round(3).to_string(index=False))
    print("\nSelected:", b["model_name"])
    print(b["selection_reason"])
    for lim in b["limitations"]:
        print("\nLimitation:", lim)
    print(f"\nSaved {MODEL_PATH} and {METADATA_PATH}")


if __name__ == "__main__":
    main()
