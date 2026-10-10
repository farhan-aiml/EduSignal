"""Seeding: the real CSV rows, and optional SYNTHETIC demo students.

Synthetic students are flagged is_demo = 1, named "Demo student NN" and
shown with a demo badge in every view. They exist so the teacher/admin
dashboards and trend charts can be demonstrated; they are not real data
and are never used for training.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from backend.config import DATASET_PATH, FEATURE_NAMES, SUBJECTS_DEFAULT, TARGET
from backend.database import database as db
from backend.utils.validation import read_csv_safely, validate_dataframe


def seed_dataset_records():
    """Load the rows of student_performance.csv as records CSV-01.. (once).
    The CSV has no IDs, names or dates, so none are invented."""
    if not db.students_df().empty:
        return
    df, err = read_csv_safely(DATASET_PATH)
    if err:
        return
    rep = validate_dataframe(df, require_target=True)
    if not rep.ok:
        return
    for i, row in rep.clean.iterrows():
        sid = f"CSV-{i + 1:02d}"
        db.upsert_student(sid, name=f"Dataset record {i + 1}", department="Unassigned",
                          class_section="Unassigned", source="dataset")
        db.add_record(sid, {f: row[f] for f in FEATURE_NAMES}, final_score=float(row[TARGET]), source="dataset")


# Realistic names for SYNTHETIC students. Every one is stored with is_demo = 1 and shown with a demo badge.
DEMO_NAMES = [
    "Rahul Sharma", "Ajay Verma", "Fahil Khan", "Priya Singh", "Ananya Gupta", "Mohammed Arif", "Sneha Patel",
    "Karan Mehta", "Ishita Roy", "Aditya Nair", "Zoya Ansari", "Rohan Das", "Kavya Reddy", "Arjun Pillai",
    "Meghna Joshi", "Siddharth Rao", "Nidhi Mishra", "Imran Sheikh", "Pooja Yadav", "Vivek Tiwari",
    "Riya Kapoor", "Harsh Chauhan", "Ayesha Siddiqui", "Manish Kumar", "Tanvi Desai", "Nikhil Bansal",
    "Shreya Iyer", "Aman Saxena", "Fatima Zaidi", "Yash Agarwal", "Divya Menon", "Kunal Bhatt",
    "Sana Malik", "Varun Chopra", "Neha Pandey", "Abhishek Singh",
]
# The three demo student logins get deliberately different stories for demos:
# Rahul is high risk and declining, Ajay is moderate but improving, Fahil is low risk and steady.
STORY = {0: (-1.55, -0.8), 1: (-1.35, 0.75), 2: (1.25, 0.0)}


def generate_demo(n_students: int = 36, weeks: int = 5, seed: int = 7) -> int:
    rng = np.random.default_rng(seed)
    depts = {"CSE": ["A", "B"], "IT": ["A"], "ECE": ["A", "B"]}
    pairs = [(d, s) for d, ss in depts.items() for s in ss]
    today = date.today()
    for i in range(n_students):
        sid = f"DEMO-{i + 1:03d}"
        dept, sec = pairs[i % len(pairs)]
        name = DEMO_NAMES[i] if i < len(DEMO_NAMES) else f"Demo student {i + 1:02d}"
        db.upsert_student(sid, name=name, department=dept, class_section=f"{dept}-{sec}", source="demo", is_demo=1)
        ability = rng.normal(0, 1)                     # latent level, drives all features together
        drift = rng.choice([-1.5, 0, 0, 1.5])         # some decline, some improve
        if i in STORY:
            ability, drift = STORY[i]
        held = 0
        attended = 0
        for w in range(weeks):
            lvl = ability + drift * w / max(1, weeks - 1) + rng.normal(0, 0.25)
            att = float(np.clip(80 + 11 * lvl + rng.normal(0, 3), 35, 100))
            vals = {
                "Attendance": round(att),
                "Assignment_Score": round(float(np.clip(74 + 13 * lvl + rng.normal(0, 4), 20, 100))),
                "Internal_Marks": round(float(np.clip(71 + 14 * lvl + rng.normal(0, 4), 15, 100))),
                "Study_Hours": float(np.clip(round((3.5 + 1.4 * lvl + rng.normal(0, .4)) * 2) / 2, 0, 10)),
                "Previous_Marks": round(float(np.clip(69 + 13 * ability + rng.normal(0, 3), 20, 100))),
            }
            held += 20
            attended += int(round(20 * att / 100))
            d = (today - timedelta(weeks=weeks - 1 - w)).isoformat()
            db.add_record(sid, vals, record_date=d, classes_held=held, classes_attended=min(attended, held), source="demo")
            if w in (0, weeks - 1):
                for sub in SUBJECTS_DEFAULT:
                    sc = float(np.clip(vals["Internal_Marks"] + rng.normal(0, 11), 10, 100))
                    db.add_subject_score(sid, sub, round(sc), d)
    from backend.utils.auth import relink_demo_students
    relink_demo_students()
    return n_students


def seed_demo_once(bundle) -> bool:
    """Load demo students automatically on first run only. If an admin removes them later,
    they are not re-added (the 'demo_seeded' setting remembers)."""
    if db.get_settings().get("demo_seeded"):
        return False
    db.save_settings({"demo_seeded": True})
    if db.demo_count() == 0:
        generate_demo()
        from backend.utils.notifications import alerts_for_all
        alerts_for_all(bundle)
    return True
