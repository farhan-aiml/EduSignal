"""Validation for manual input, uploaded CSVs and the training dataset.

Every function returns structured results instead of raising, so the UI
can show a clear message and never crash on bad data.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from config import FEATURES, FEATURE_NAMES, TARGET, TARGET_RANGE

OPTIONAL_COLUMNS = ["Student_ID", "Name", "Department", "Class_Section", "Record_Date",
                    "Classes_Held", "Classes_Attended", TARGET]


@dataclass
class ValidationReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)      # block the import
    warnings: list[str] = field(default_factory=list)    # import allowed, user informed
    clean: pd.DataFrame | None = None                    # rows that passed
    rejected: pd.DataFrame | None = None                 # rows that failed, with reason

    def error(self, msg: str):
        self.ok = False
        self.errors.append(msg)


def validate_inputs(values: dict) -> list[str]:
    """Validate one set of model inputs. Returns a list of problems (empty = valid)."""
    problems = []
    for name, spec in FEATURES.items():
        v = values.get(name)
        if v is None or (isinstance(v, str) and not v.strip()):
            problems.append(f"{spec['label']} is missing.")
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            problems.append(f"{spec['label']} must be a number (got {v!r}).")
            continue
        if not np.isfinite(v) or not spec["min"] <= v <= spec["max"]:
            problems.append(f"{spec['label']} must be between {spec['min']} and {spec['max']} (got {v:g}).")
    return problems


def read_csv_safely(source) -> tuple[pd.DataFrame | None, str | None]:
    """Read a CSV from a path or uploaded file. Returns (df, error_message)."""
    try:
        if hasattr(source, "getvalue"):
            raw = source.getvalue()
            if not raw:
                return None, "File khaali hai."
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                return None, "File UTF-8 text nahi hai. Ise 'CSV UTF-8' mein save karke dobara upload karein."
            df = pd.read_csv(io.StringIO(text))
        else:
            df = pd.read_csv(source)
    except FileNotFoundError:
        return None, f"File nahi mili: {source}"
    except pd.errors.EmptyDataError:
        return None, "File mein koi data nahi hai."
    except pd.errors.ParserError as e:
        return None, f"File CSV ki tarah padhi nahi ja saki: {e}"
    except Exception as e:  # corrupted/odd files
        return None, f"File padhi nahi ja saki: {e}"
    df.columns = [str(c).strip() for c in df.columns]
    return df, None


def validate_dataframe(df: pd.DataFrame, require_target: bool = False) -> ValidationReport:
    """Validate a student-records dataframe.

    Checks: required columns, data types, missing values, value ranges,
    duplicate rows and duplicate (Student_ID, Record_Date) keys.
    Bad rows are separated out rather than silently dropped.
    """
    rep = ValidationReport()
    if df is None or df.empty:
        rep.error("Koi row nahi mili.")
        return rep

    required = FEATURE_NAMES + ([TARGET] if require_target else [])
    missing_cols = [c for c in required if c not in df.columns]
    if missing_cols:
        rep.error("Zaroori column(s) missing hain: " + ", ".join(missing_cols)
                  + ". Zaroori: " + ", ".join(required) + ".")
        return rep

    unknown = [c for c in df.columns if c not in FEATURE_NAMES + OPTIONAL_COLUMNS]
    if unknown:
        rep.warnings.append("Anjaan column(s) ignore kiye gaye: " + ", ".join(unknown) + ".")

    work = df.copy()
    reasons = pd.Series([""] * len(work), index=work.index, dtype="object")

    def flag(mask, text):
        nonlocal reasons
        reasons = reasons.where(~mask, reasons + text + "; ")

    numeric_cols = FEATURE_NAMES + [c for c in [TARGET, "Classes_Held", "Classes_Attended"] if c in work.columns]
    for col in numeric_cols:
        original = work[col]
        converted = pd.to_numeric(original, errors="coerce")
        bad_type = original.notna() & converted.isna()
        if bad_type.any():
            flag(bad_type, f"{col} number nahi hai")
        work[col] = converted

    for col in FEATURE_NAMES + ([TARGET] if require_target else []):
        miss = work[col].isna() & reasons.eq("")
        if miss.any():
            flag(miss, f"{col} missing hai")

    ranges = {n: (s["min"], s["max"]) for n, s in FEATURES.items()}
    if TARGET in work.columns:
        ranges[TARGET] = TARGET_RANGE
    for col, (lo, hi) in ranges.items():
        out = work[col].notna() & ((work[col] < lo) | (work[col] > hi))
        if out.any():
            flag(out, f"{col} range {lo}-{hi} se bahar hai")

    if {"Classes_Held", "Classes_Attended"} <= set(work.columns):
        bad = work["Classes_Attended"] > work["Classes_Held"]
        if bad.any():
            flag(bad, "Classes_Attended, Classes_Held se zyada hai")

    if "Record_Date" in work.columns:
        parsed = pd.to_datetime(work["Record_Date"], errors="coerce")
        bad = work["Record_Date"].notna() & parsed.isna()
        if bad.any():
            flag(bad, "Record_Date sahi tareekh nahi hai (YYYY-MM-DD likhein)")
        work["Record_Date"] = parsed.dt.strftime("%Y-%m-%d")

    dup = work.duplicated(keep="first")
    if dup.any():
        rep.warnings.append(f"{int(dup.sum())} bilkul duplicate row(s) skip ki gayi.")
    if "Student_ID" in work.columns:
        key = ["Student_ID"] + (["Record_Date"] if "Record_Date" in work.columns else [])
        key_dup = work.duplicated(subset=key, keep="first") & ~dup
        if key_dup.any():
            flag(key_dup, "duplicate " + "/".join(key))

    bad_rows = reasons.ne("")
    rep.rejected = work[bad_rows].assign(Reason=reasons[bad_rows].str.rstrip("; "))
    rep.clean = work[~bad_rows & ~dup].reset_index(drop=True)
    if bad_rows.any():
        rep.warnings.append(f"{int(bad_rows.sum())} row(s) validation mein fail hui aur import nahi hongi.")
    if rep.clean.empty:
        rep.error("Validation ke baad koi sahi row nahi bachi.")
    return rep


def data_quality_report(df: pd.DataFrame) -> dict:
    """Descriptive quality report of a training dataset (no modelling)."""
    num = df.select_dtypes("number")
    q1, q3 = num.quantile(0.25), num.quantile(0.75)
    iqr = q3 - q1
    outliers = ((num < q1 - 1.5 * iqr) | (num > q3 + 1.5 * iqr)).sum()
    corr = num.corr()
    upper = corr.where(np.triu(np.ones(corr.shape, dtype=bool), k=1))
    return {
        "rows": int(len(df)),
        "columns": int(df.shape[1]),
        "missing": df.isna().sum().to_dict(),
        "duplicates": int(df.duplicated().sum()),
        "describe": num.describe().T,
        "outliers": outliers.to_dict(),
        "corr": corr,
        "min_pairwise_corr": float(np.nanmin(upper.values)) if upper.notna().any().any() else float("nan"),
    }
