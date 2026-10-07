"""Request and response models for the ClearBed API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RunRequest(BaseModel):
    """Start a copilot run for one worklist stay."""

    stay_id: str


class DecisionRequest(BaseModel):
    """One human decision. ``approve`` records status ``sent`` and does not transmit."""

    facility_ccn: str
    decision: Literal["approve", "reject"]
    note: str = ""
    actor: str = "case_manager"


class WorklistRow(BaseModel):
    """One pseudonymized census row."""

    stay_id: str
    patient_pseudo_id: str
    age_band: str
    condition_group: str
    payer_type: str
    day_of_stay: int
    expected_los: float
    stuck_prob: float
    risk_tier: str
    predicted_barrier: str
    predicted_avoidable_days: float
    top_reasons: list[Any] = Field(default_factory=list)


class ReferralEvent(BaseModel):
    """One row on the referral timeline."""

    referral_id: str
    stay_id: str
    facility_ccn: str
    facility_name: str
    status: str
    note: str
    actor: str
    created_at: str | None = None


class LeadershipResponse(BaseModel):
    """Dashboard payload. Cost is the configured assumption."""

    total_census: int
    high_risk_count: int
    projected_avoidable_bed_days: float
    estimated_cost: float
    cost_per_bed_day: float
    cost_note: str
    scored_at: str | None = None
    series: list[dict[str, Any]]
    series_note: str
    simulated_backcast: bool
    referrals_by_status: dict[str, int]
    banner: str = "Synthetic data — demo only"
