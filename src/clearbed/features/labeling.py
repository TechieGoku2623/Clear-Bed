"""Auditable discharge-barrier labels for Synthea stays.

Synthea has no discharge disposition and no delay reason. Labels are assigned
by the rules in ``dbt/seeds/labeling_rules.csv``. Each rule has a priority, a
transparent predicate, a probability, and a range of avoidable days. A stay
walks the rules in priority order. The first rule whose predicate matches and
whose seeded coin flip succeeds wins. The coin flip is a SHA-256 of the stay
id and the rule id, so the same stay always gets the same label.

``is_stuck`` is true when avoidable days are at least 2.

Replacement path: with PhysioNet credentialing, replace this function with
labels derived from MIMIC-IV ``admissions.discharge_location`` and length of
stay. Keep the rest of the feature table.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any

import pandas as pd

BARRIER_TYPES = (
    "post_acute_placement",
    "payer_pending",
    "guardianship_capacity",
    "home_services",
    "none",
)


def _blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    return str(value).strip() == ""


def _flag(value: Any) -> int:
    if _blank(value):
        return 0
    return int(float(value))


def _number(value: Any) -> float | None:
    if _blank(value):
        return None
    return float(value)


def unit_interval(key: str) -> float:
    """Return a stable number in ``[0, 1)`` for ``key``."""
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) / 0xFFFFFFFF


def rule_matches(stay: dict[str, Any], rule: dict[str, Any]) -> bool:
    """Return whether ``stay`` satisfies the predicate on ``rule``."""
    min_age = _number(rule.get("min_age"))
    max_age = _number(rule.get("max_age"))
    age = float(stay.get("age_at_admit") or 0)
    if min_age is not None and age < min_age:
        return False
    if max_age is not None and age > max_age:
        return False
    if not _blank(rule.get("condition_groups")):
        allowed = {
            part.strip() for part in str(rule["condition_groups"]).split("|") if part.strip()
        }
        if str(stay.get("condition_group") or "") not in allowed:
            return False
    if not _blank(rule.get("payer_types")):
        allowed_payers = {
            part.strip() for part in str(rule["payer_types"]).split("|") if part.strip()
        }
        if str(stay.get("payer_type") or "") not in allowed_payers:
            return False
    if _flag(rule.get("requires_dementia")) and not _flag(stay.get("flag_dementia")):
        return False
    if _flag(rule.get("requires_lives_alone")) and not _flag(stay.get("lives_alone_proxy")):
        return False
    if _flag(rule.get("requires_home_o2")) and not _flag(stay.get("flag_home_o2")):
        return False
    if _flag(rule.get("requires_chf_or_copd")) and not (
        _flag(stay.get("flag_chf")) or _flag(stay.get("flag_copd"))
    ):
        return False
    return True


def _avoidable_days(stay_id: str, rule: dict[str, Any]) -> int:
    low = int(float(rule["avoidable_min"]))
    high = int(float(rule["avoidable_max"]))
    if high < low:
        low, high = high, low
    span = high - low
    draw = unit_interval(f"{stay_id}|avoid|{rule['rule_id']}")
    return low + min(span, int(draw * (span + 1)))


def assign_label(stay: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """Assign one stay's barrier, avoidable days, and stuck flag."""
    stay_id = str(stay["stay_id"])
    chosen = rules[-1]
    for rule in rules:
        if not rule_matches(stay, rule):
            continue
        draw = unit_interval(f"{stay_id}|{rule['rule_id']}")
        if draw < float(rule["probability"]):
            chosen = rule
            break
    days = _avoidable_days(stay_id, chosen)
    barrier = str(chosen["barrier_type"])
    if barrier not in BARRIER_TYPES:
        raise ValueError(f"Unknown barrier_type on rule {chosen['rule_id']}: {barrier}")
    return {
        "stay_id": stay_id,
        "barrier_type": barrier,
        "avoidable_days": int(days),
        "is_stuck": int(days >= 2),
        "rule_id": str(chosen["rule_id"]),
        "label_note": str(chosen.get("notes") or ""),
    }


def assign_labels(stays: pd.DataFrame, rules: pd.DataFrame) -> pd.DataFrame:
    """Label every stay. Rules are applied in ascending ``priority``."""
    ordered = rules.sort_values(["priority", "rule_id"]).to_dict(orient="records")
    if not ordered:
        raise ValueError("labeling_rules is empty")
    labeled = [assign_label(row, ordered) for row in stays.to_dict(orient="records")]
    return pd.DataFrame(labeled)


def route_barrier(features: dict[str, Any]) -> str:
    """Choose the copilot workflow from auditable rules, then the model.

    Clinical rules outrank the model so a hip fracture at 80 or a dementia
    patient who lives alone is not dropped because a score said ``none``.
    The model prediction is used only when no rule fires.
    """
    age = float(features.get("age_at_admit") or 0)
    group = str(features.get("condition_group") or "")
    if _flag(features.get("flag_dementia")) and _flag(features.get("lives_alone_proxy")):
        return "guardianship_capacity"
    if age >= 75 and group in {"hip_fracture", "stroke"}:
        return "post_acute_placement"
    payer = str(features.get("payer_type") or "")
    if payer == "none" or _flag(features.get("medicaid_pending")):
        return "payer_pending"
    chronic = _flag(features.get("flag_chf")) or _flag(features.get("flag_copd"))
    if chronic and _flag(features.get("flag_home_o2")):
        return "home_services"
    predicted = str(features.get("predicted_barrier") or "none")
    if predicted in BARRIER_TYPES and predicted != "none":
        return predicted
    return "none"
