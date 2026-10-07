"""Data-quality gates fail on small samples, leakage, and sparse features."""

from __future__ import annotations

import pandas as pd

from clearbed.features.quality_report import evaluate_checks


def test_evaluate_checks_passes_a_clean_frame() -> None:
    nulls = pd.DataFrame({"column": ["age_at_admit"], "null_rate": [0.0]})
    assert evaluate_checks(n_stays=600, nulls=nulls, leaked=[]) == []


def test_evaluate_checks_flags_critical_problems() -> None:
    nulls = pd.DataFrame({"column": ["payer_type"], "null_rate": [0.2]})
    failures = evaluate_checks(n_stays=10, nulls=nulls, leaked=["los_days"], min_stays=500)
    blob = " ".join(failures)
    assert "Fewer than 500" in blob
    assert "los_days" in blob
    assert "payer_type" in blob
