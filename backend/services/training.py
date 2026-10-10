"""Training-data assembly and readiness.

Sources (real data only):
  * backend/data/student_performance.csv (the original dataset)
  * database records that have an actual Final_Score and are NOT synthetic demo data
    (sources: CSV import, records saved by teachers, computed snapshots)
Demo students are never used for training. Rows are validated with the same rules as imports, exact
duplicates are dropped (a row imported and also appended to the CSV is counted once), and missing or
out-of-range values are rejected with a reason.
"""
from __future__ import annotations

import pandas as pd

from backend.config import DATASET_PATH, FEATURE_NAMES, TARGET
from backend.database import database as db
from backend.ml.train_model import HOLDOUT_MIN_ROWS, RECOMMENDED_ROWS, SMALL_DATA_ROWS
from backend.utils.validation import read_csv_safely, validate_dataframe

MIN_ROWS = 5

REQUIRED_DATA = [
    ("Attendance", "Term attendance % (0-100) at the time of the record"),
    ("Assignment_Score", "Average assignment mark (0-100)"),
    ("Internal_Marks", "Average internal test mark (0-100)"),
    ("Study_Hours", "Average self-study hours per day (0-24)"),
    ("Previous_Marks", "Previous term's final mark (0-100)"),
    ("Final_Score", "The ACTUAL final result (0-100), known only after the exam: this is what the model learns"),
]


def assemble() -> tuple[pd.DataFrame, dict]:
    """Returns (clean training rows, report)."""
    parts, report = [], {"sources": {}, "rejected": [], "duplicates": 0, "demo_excluded": 0}
    csv, err = read_csv_safely(DATASET_PATH)
    if err is None and csv is not None and TARGET in csv.columns:
        parts.append(csv.assign(_source="student_performance.csv"))
    rec = db.records_df()
    if not rec.empty:
        with_target = rec[rec["final_score"].notna()]
        report["demo_excluded"] = int(with_target["is_demo"].astype(bool).sum())
        real = with_target[(~with_target["is_demo"].astype(bool)) & (with_target["source"] != "dataset")]
        if not real.empty:
            parts.append(real[FEATURE_NAMES].assign(**{TARGET: real["final_score"].values},
                                                    _source=("database: " + real["source"]).values))
    if not parts:
        return pd.DataFrame(columns=FEATURE_NAMES + [TARGET]), report
    raw = pd.concat(parts, ignore_index=True)
    report["sources"] = raw["_source"].value_counts().to_dict()          # rows found per source
    cols = FEATURE_NAMES + [TARGET]
    as_num = raw[cols].apply(pd.to_numeric, errors="coerce")
    dup = as_num.duplicated(keep="first")                                # same row in two sources counts once
    report["duplicates"] = int(dup.sum())
    rep = validate_dataframe(raw.loc[~dup, cols].reset_index(drop=True), require_target=True)
    if rep.rejected is not None and not rep.rejected.empty:
        report["rejected"] = rep.rejected["Reason"].value_counts().to_dict()
    clean = rep.clean if rep.clean is not None else pd.DataFrame(columns=cols)
    report["rows"] = len(clean)
    return clean, report


def readiness(report: dict) -> dict:
    n = report.get("rows", 0)
    if n < MIN_ROWS:
        level, msg = "blocked", f"Training needs at least {MIN_ROWS} rows; there are {n}."
    elif n < SMALL_DATA_ROWS:
        level, msg = "demo", (f"Only {n} rows: suitable for a demo only. No separate test set is possible, "
                              "so the results are not reliable.")
    elif n < HOLDOUT_MIN_ROWS:
        level, msg = "weak", f"{n} rows: cross-validated, but a separate test set needs {HOLDOUT_MIN_ROWS}+ rows."
    elif n < RECOMMENDED_ROWS:
        level, msg = "fair", f"{n} rows: evaluated on a separate test set. {RECOMMENDED_ROWS}+ rows are recommended for reliable results."
    else:
        level, msg = "good", f"{n} rows: evaluated on a separate test set."
    return {"level": level, "message": msg, "rows": n, "needed_for_test_set": max(0, HOLDOUT_MIN_ROWS - n),
            "needed_recommended": max(0, RECOMMENDED_ROWS - n)}
