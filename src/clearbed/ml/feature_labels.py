"""Model matrix columns and the plain-English names shown to case managers.

Gender and race are intentionally absent from the model matrix. They remain
on the feature table so the fairness report can measure them, and they are
not sent to the worklist.
"""

from __future__ import annotations

NUMERIC_FEATURES: list[str] = [
    "age_at_admit",
    "admit_month",
    "admit_dow",
    "prior_admits_12m",
    "prior_ed_visits_12m",
    "n_active_meds",
    "expected_los_days",
    "flag_dementia",
    "flag_ckd_dialysis",
    "flag_copd",
    "flag_chf",
    "flag_obesity",
    "flag_behavioral",
    "flag_substance",
    "flag_home_o2",
    "lives_alone_proxy",
]

CATEGORICAL_FEATURES: list[str] = [
    "condition_group",
    "payer_type",
    "age_band",
]

FAIRNESS_COLUMNS: list[str] = ["gender", "race", "payer_type"]

LEAKAGE_COLUMNS: frozenset[str] = frozenset(
    {"los_days", "stop_ts", "avoidable_days", "is_stuck", "barrier_type", "deathdate"}
)

FEATURE_LABELS: dict[str, str] = {
    "age_at_admit": "age at admission",
    "admit_month": "admission month",
    "admit_dow": "day of week admitted",
    "prior_admits_12m": "inpatient admissions in the prior year",
    "prior_ed_visits_12m": "emergency visits in the prior year",
    "n_active_meds": "number of active medications",
    "expected_los_days": "typical length of stay for this condition and age",
    "flag_dementia": "dementia on the problem list",
    "flag_ckd_dialysis": "kidney disease or dialysis",
    "flag_copd": "COPD",
    "flag_chf": "heart failure",
    "flag_obesity": "obesity",
    "flag_behavioral": "a behavioral health diagnosis",
    "flag_substance": "a substance use diagnosis",
    "flag_home_o2": "home oxygen",
    "lives_alone_proxy": "lives alone (synthetic proxy, not a charted social history)",
    "condition_group": "primary condition",
    "payer_type": "payer at admission",
    "age_band": "age band",
}


def readable_feature(column: str) -> str:
    """Return a case-manager label for a model column, including dummy columns."""
    if column in FEATURE_LABELS:
        return FEATURE_LABELS[column]
    for categorical in CATEGORICAL_FEATURES:
        prefix = f"{categorical}_"
        if column.startswith(prefix):
            base = FEATURE_LABELS.get(categorical, categorical.replace("_", " "))
            level = column[len(prefix) :].replace("_", " ")
            return f"{base} is {level}"
    return column.replace("_", " ")


def model_feature_columns() -> list[str]:
    """Return the snapshot columns the model is allowed to see."""
    return [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]
