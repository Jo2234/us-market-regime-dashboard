"""Deterministic persistence over trading observations; no fitted parameters."""
from app.services.calendar import missed_sessions
from datetime import date


def stabilize(rows, *, persistence=5, label_key="regime_label", strong=None):
    if persistence < 1:
        raise ValueError("Persistence must be positive")
    official = candidate = previous_date = None
    candidate_days = duration = 0
    result = []
    for row in rows:
        raw = row.get(label_key)
        day = date.fromisoformat(row["date"])
        if previous_date and day <= previous_date:
            raise ValueError("Stability inputs must have unique increasing dates")
        if previous_date and missed_sessions(previous_date, day) > 1:
            candidate, candidate_days = None, 0
        previous_date = day
        override = bool(raw and strong and strong(row))
        changed = False
        if official is None and raw:
            official, duration = raw, 1
        else:
            duration += bool(official)
            if not raw or raw == official:
                candidate, candidate_days = None, 0
            else:
                candidate_days = candidate_days + 1 if candidate == raw else 1
                candidate = raw
                if candidate_days >= persistence or override:
                    official, duration, candidate, candidate_days = raw, 1, None, 0
                    changed = True
        result.append({**row, "raw_label": raw, "official_label": official,
                       "days_in_regime": duration, "emerging_label": candidate,
                       "emerging_days": candidate_days, "persistence_days": persistence,
                       "strong_override": override and changed})
    return result


def changes(rows, key="official_label"):
    labels = [r[key] for r in rows if r.get(key) is not None]
    return sum(a != b for a, b in zip(labels, labels[1:]))
