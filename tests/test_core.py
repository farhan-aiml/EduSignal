"""Core logic tests (no Streamlit needed).  Run:  python -m tests.test_core"""
import pandas as pd

from config import DEFAULT_SETTINGS as S
from ml.explain import explain_one
from ml.predict import load_bundle, predict_one
from ml.train_model import train
from utils.attendance import attendance_status
from utils.risk_engine import assess
from utils.validation import validate_dataframe, validate_inputs

LOW = dict(Attendance=60, Assignment_Score=55, Internal_Marks=50, Study_Hours=1, Previous_Marks=48)


def test_model_monotonic_and_shapley_additive():
    b, err = load_bundle()
    if b is None:
        b = train()
    assert b["monotonic_check"]["passed"], "selected model must pass the sanity check"
    e = explain_one(b, LOW)
    assert abs(e["base"] + sum(e["contributions"].values()) - predict_one(b, LOW)) < 1e-6
    for f in LOW:  # raising any input must not lower the prediction
        assert predict_one(b, dict(LOW, **{f: LOW[f] + 10})) >= predict_one(b, LOW) - 0.5


def test_attendance_math():
    a = attendance_status(70, 75, held=40, attended=28)
    assert a["classes_needed"] == 8 and (28 + 8) / (40 + 8) >= 0.75 > (28 + 7) / (40 + 7)
    assert attendance_status(90, 75, 40, 36)["can_miss"] == 8
    assert attendance_status(70, 100, 40, 28)["classes_needed"] is None


def test_risk_levels_and_trend():
    assert assess(LOW, 52.9, S)["level"] == "High"
    good = dict(Attendance=95, Assignment_Score=90, Internal_Marks=88, Study_Hours=5, Previous_Marks=85)
    assert assess(good, 90, S)["level"] == "Low"
    r = assess(good, 90, S, history=[99])
    assert r["trend"]["declining"] and any(f["key"] == "decline" for f in r["factors"])
    assert not assess(good, 90, S)["trend"]["available"]   # no history -> no guessed trend


def test_validation():
    assert validate_inputs(dict(LOW, Attendance=120))
    assert not validate_inputs(LOW)
    df = pd.DataFrame([LOW, dict(LOW, Study_Hours="x"), LOW])
    rep = validate_dataframe(df)
    assert rep.ok and len(rep.clean) == 1 and len(rep.rejected) == 1
    assert not validate_dataframe(pd.DataFrame({"Attendance": [1]})).ok


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("passed", name)
