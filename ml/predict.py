"""Model loading and prediction.

Loading never crashes the app: failures return (None, message). If the
saved model is missing or was written by an incompatible library version,
the caller can retrain from the dataset (see app.get_model).
"""
from __future__ import annotations

import warnings

import joblib
import numpy as np
import pandas as pd

from config import FEATURE_NAMES, FEATURES, MODEL_PATH

GRADES = [(90, "A+"), (80, "A"), (70, "B"), (60, "C"), (0, "D")]          # kept from the original app
CATEGORIES = [(85, "Excellent"), (70, "Good"), (50, "Average"), (0, "Poor")]


def load_bundle(path=MODEL_PATH):
    if not path.exists():
        return None, f"No trained model found at {path.name}."
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", category=UserWarning)  # version mismatch -> treat as failure
            obj = joblib.load(path)
    except Exception as e:
        return None, f"The saved model could not be loaded ({type(e).__name__}: {e})."
    if not isinstance(obj, dict) or "pipeline" not in obj:
        return None, "The saved model is in the old format (a bare estimator without metadata)."
    return obj, None


def to_frame(values: dict | pd.DataFrame) -> pd.DataFrame:
    if isinstance(values, pd.DataFrame):
        return values[FEATURE_NAMES].astype(float)
    return pd.DataFrame([[float(values[f]) for f in FEATURE_NAMES]], columns=FEATURE_NAMES)


def predict_many(bundle, df: pd.DataFrame) -> np.ndarray:
    pred = bundle["pipeline"].predict(to_frame(df))
    return np.clip(pred, 0, 100)   # scores live on a 0-100 scale


def predict_one(bundle, values: dict) -> float:
    return float(predict_many(bundle, to_frame(values))[0])


def grade_for(score: float) -> str:
    return next(g for cut, g in GRADES if score >= cut)


def category_for(score: float) -> str:
    return next(c for cut, c in CATEGORIES if score >= cut)


def percentile_in_training(bundle, score: float) -> tuple[int, int]:
    """How many training records have a lower actual final score. Honest
    replacement for the old hard-coded 'Top 10%' labels."""
    t = bundle.get("target_values") or []
    return int(sum(v < score for v in t)), len(t)


def extrapolation_notes(bundle, values: dict) -> list[str]:
    """Inputs outside what the model saw in training are extrapolation."""
    notes = []
    for f, (lo, hi) in bundle.get("training_ranges", {}).items():
        v = float(values[f])
        if v < lo or v > hi:
            notes.append(f"{FEATURES[f]['label']} {v:g} (trained on {lo:g}-{hi:g})")
    return notes
