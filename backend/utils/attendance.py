"""Attendance intelligence: gap to target and classes needed.

If a student has attended `a` of `t` classes and attends the next x in a row,
attendance becomes (a + x) / (t + x). Solving (a + x)/(t + x) >= T gives
x >= (T*t - a) / (1 - T). Reaching a 100% target after any absence is
mathematically impossible, which the function reports rather than hiding.
"""
from __future__ import annotations

import math


def attendance_status(percent: float, target: float, held: int | None = None, attended: int | None = None) -> dict:
    out = {"current": percent, "target": target, "gap": round(max(0.0, target - percent), 1),
           "below_target": percent < target, "classes_needed": None, "can_miss": None, "note": None}
    if not held or attended is None:
        out["note"] = "Enter classes held and attended to calculate classes needed."
        return out
    if attended > held or held <= 0:
        out["note"] = "Classes attended cannot exceed classes held."
        return out
    T = target / 100
    out["current"] = round(100 * attended / held, 1)
    out["gap"] = round(max(0.0, target - out["current"]), 1)
    out["below_target"] = out["current"] < target
    if out["below_target"]:
        if T >= 1:
            out["note"] = "A 100% target cannot be reached once any class has been missed."
        else:
            out["classes_needed"] = math.ceil((T * held - attended) / (1 - T) - 1e-9)
    else:
        out["can_miss"] = math.floor((attended - T * held) / T + 1e-9) if T > 0 else None
    return out
