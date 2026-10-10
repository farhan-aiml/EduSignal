"""Explainable AI: exact Shapley values (the quantity SHAP estimates).

With 5 features there are only 2^5 = 32 feature coalitions, so Shapley
values can be computed exactly instead of approximated:

    v(S)  = average prediction when features in S take the student's values
            and the rest take values from the background (training) data
    phi_i = sum over S not containing i of
            |S|! (d-|S|-1)! / d!  *  (v(S + i) - v(S))

Properties: contributions add up exactly to (prediction - average
prediction), and the method works for any model (linear or tree). This is
the 'interventional' Shapley definition used by shap.KernelExplainer.

Caveat shown in the UI: with highly correlated features, attributions
describe how the MODEL uses each input, not what causes a student's score.
"""
from __future__ import annotations

from itertools import combinations
from math import factorial

import numpy as np
import pandas as pd

from backend.config import FEATURE_NAMES, FEATURES
from backend.ml.predict import predict_many, to_frame

MAX_BACKGROUND = 100


def _background(bundle) -> pd.DataFrame:
    bg = pd.DataFrame(bundle["background"])[FEATURE_NAMES].astype(float)
    if len(bg) > MAX_BACKGROUND:
        bg = bg.sample(MAX_BACKGROUND, random_state=0)
    return bg.reset_index(drop=True)


def shapley_values(bundle, values: dict | pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Return (contributions per row x feature, base value)."""
    X = to_frame(values).reset_index(drop=True)
    bg = _background(bundle)
    d, nb = len(FEATURE_NAMES), len(bg)
    masks = [frozenset(c) for k in range(d + 1) for c in combinations(range(d), k)]
    idx = {m: i for i, m in enumerate(masks)}

    # Build every (row, coalition, background) combination and predict once.
    bgv = bg.values
    blocks = []
    for x in X.values:
        for m in masks:
            block = bgv.copy()
            cols = list(m)
            if cols:
                block[:, cols] = x[cols]
            blocks.append(block)
    preds = predict_many(bundle, pd.DataFrame(np.vstack(blocks), columns=FEATURE_NAMES))
    v = preds.reshape(len(X), len(masks), nb).mean(axis=2)     # rows x coalitions

    weights = {k: factorial(k) * factorial(d - k - 1) / factorial(d) for k in range(d)}
    phi = np.zeros((len(X), d))
    for i in range(d):
        for m in masks:
            if i in m:
                continue
            phi[:, i] += weights[len(m)] * (v[:, idx[m | {i}]] - v[:, idx[m]])
    base = float(v[:, idx[frozenset()]].mean())
    return pd.DataFrame(phi, columns=FEATURE_NAMES), base


def explain_one(bundle, values: dict) -> dict:
    contrib, base = shapley_values(bundle, values)
    c = contrib.iloc[0].sort_values(key=abs, ascending=False)
    return {"base": base, "contributions": c.to_dict(), "prediction": base + float(c.sum())}


def global_importance(bundle) -> pd.Series:
    """Mean |Shapley value| over the training data: how much each input moves predictions on average."""
    contrib, _ = shapley_values(bundle, pd.DataFrame(bundle["background"]))
    return contrib.abs().mean().sort_values(ascending=False)


def narrative(exp: dict, threshold: float = 0.5) -> str:
    """Plain-language summary built only from the computed contributions."""
    c = exp["contributions"]
    neg = [k for k, v in c.items() if v < -threshold]
    pos = [k for k, v in c.items() if v > threshold]
    lab = lambda ks: " and ".join(FEATURES[k]["label"].lower() for k in ks[:2])
    base = exp["base"]
    parts = [f"The average predicted score in the training data is {base:.1f}."]
    if neg:
        parts.append(f"Your prediction is pulled down mainly by {lab(neg)}.")
    if pos:
        parts.append(f"It is lifted mainly by {lab(pos)}.")
    if not neg and not pos:
        parts.append("Your inputs are close to the average, so no single factor moves the prediction much.")
    return " ".join(parts)


def sensitivity(bundle, values: dict, feature: str, points: int = 25) -> pd.DataFrame:
    """Prediction as one input varies and the others stay fixed."""
    spec = FEATURES[feature]
    grid = np.linspace(spec["min"], min(spec["max"], 12 if feature == "Study_Hours" else spec["max"]), points)
    X = pd.DataFrame([to_frame(values).iloc[0].values] * points, columns=FEATURE_NAMES)
    X[feature] = grid
    return pd.DataFrame({feature: grid, "Predicted": predict_many(bundle, X)})
