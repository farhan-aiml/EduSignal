"""Model registry, prediction intervals, and honest evaluation of predictions and risk flags.

Evaluation only uses records that have a real final score AND were not part of the training
data (source != 'dataset'), so it never reports in-sample accuracy as if it were validation.
"""
from __future__ import annotations

import hashlib
import json

import numpy as np
import pandas as pd

from backend.config import DATASET_PATH, FEATURE_NAMES
from backend.database import database as db
from backend.ml.predict import predict_many

MIN_EVAL_ROWS = 10


def version_of(bundle: dict) -> str:
    raw = f"{bundle['model_name']}|{bundle['trained_at']}|{bundle['training_rows']}"
    return "v" + bundle["trained_at"][:10].replace("-", "") + "-" + hashlib.sha1(raw.encode()).hexdigest()[:8]


def _dataset_hash() -> str | None:
    try:
        return hashlib.sha256(DATASET_PATH.read_bytes()).hexdigest()
    except OSError:
        return None


def register(bundle: dict) -> str:
    """Record the bundle in model_versions (once) and mark it active. Returns its version string."""
    v = version_of(bundle)
    m = bundle["metrics"]
    with db.connect() as con:
        con.execute("INSERT OR IGNORE INTO model_versions(version, model_name, trained_at, training_rows, cv_scheme, "
                    "mae, rmse, r2, interval_p80, dataset_sha256, sklearn_version, metrics_json, registered_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (v, bundle["model_name"], bundle["trained_at"], bundle["training_rows"], bundle.get("cv_scheme"),
                     m.get("MAE"), m.get("RMSE"), m.get("R2"), interval_half_width(bundle), _dataset_hash(),
                     bundle.get("sklearn_version"), json.dumps(bundle.get("comparison"), default=str), db.now()))
        con.execute("UPDATE model_versions SET is_active = (version = ?)", (v,))
    return v


def versions_df() -> pd.DataFrame:
    return db.query_df("SELECT version, model_name, trained_at, training_rows, cv_scheme, ROUND(mae, 2) AS mae, "
                       "ROUND(rmse, 2) AS rmse, ROUND(r2, 3) AS r2, ROUND(interval_p80, 2) AS interval_p80, is_active "
                       "FROM model_versions ORDER BY id DESC")


def interval_half_width(bundle: dict) -> float:
    """Half-width of an ~80% prediction interval from cross-validated residuals (falls back to 1.28 x RMSE)."""
    w = bundle.get("cv_abs_residual_p80")
    if w is None:
        w = 1.2816 * float(bundle["metrics"]["RMSE"])
    return float(w)


def interval(bundle: dict, predicted: float) -> tuple[float, float]:
    w = interval_half_width(bundle)
    return max(0.0, round(predicted - w, 1)), min(100.0, round(predicted + w, 1))


def evaluate_against_outcomes(bundle: dict, settings: dict) -> dict:
    """Compare predictions and High-risk flags with actual final scores on records the model never saw."""
    from backend.utils.risk_engine import assess
    rec = db.records_df()
    if rec.empty:
        return {"rows": 0, "enough": False}
    rec = rec[rec["final_score"].notna() & (rec["source"] != "dataset")]
    n = len(rec)
    out = {"rows": n, "enough": n >= MIN_EVAL_ROWS, "min_rows": MIN_EVAL_ROWS}
    if n == 0:
        return out
    pred = predict_many(bundle, rec)
    y = rec["final_score"].astype(float).to_numpy()
    out["mae"] = float(np.mean(np.abs(pred - y)))
    out["rmse"] = float(np.sqrt(np.mean((pred - y) ** 2)))
    lo_hi = [interval(bundle, p) for p in pred]
    out["interval_coverage"] = float(np.mean([lo <= t <= hi for (lo, hi), t in zip(lo_hi, y)]))
    flagged = np.array([assess({f: float(r[f]) for f in FEATURE_NAMES}, float(p), settings)["level"] == "High"
                        for (_, r), p in zip(rec.iterrows(), pred)])
    failed = y < settings["pass_score"]
    tp, fp, fn = int(np.sum(flagged & failed)), int(np.sum(flagged & ~failed)), int(np.sum(~flagged & failed))
    out.update(tp=tp, fp=fp, fn=fn, tn=int(np.sum(~flagged & ~failed)), positives=int(failed.sum()))
    out["precision"] = tp / (tp + fp) if tp + fp else None
    out["recall"] = tp / (tp + fn) if tp + fn else None
    p, r = out["precision"], out["recall"]
    out["f1"] = 2 * p * r / (p + r) if p and r else None
    return out
