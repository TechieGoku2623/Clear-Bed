"""Risk tiers and the plain-English reason payload."""

from __future__ import annotations

from clearbed.ml.score import pseudonym, risk_tier


def test_risk_tiers() -> None:
    assert risk_tier(0.6) == "high"
    assert risk_tier(0.59) == "medium"
    assert risk_tier(0.3) == "medium"
    assert risk_tier(0.29) == "low"


def test_pseudonym_is_stable_and_short() -> None:
    assert pseudonym("patient-1") == pseudonym("patient-1")
    assert len(pseudonym("patient-1")) == 12
    assert pseudonym("patient-1") != "patient-1"
