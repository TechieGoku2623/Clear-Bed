"""Score a simulated current census and write the case-manager worklist.

The N most recent inpatient stays stand in for patients still in a bed.
``day_of_stay`` is simulated. Patient ids on the worklist are pseudonyms.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from clearbed.config import Settings, get_settings
from clearbed.features.labeling import unit_interval
from clearbed.logging import get_logger, log_event
from clearbed.ml.train import (
    explain_frame,
    load_training_frame,
    predict_barrier,
    predict_days,
    predict_stuck,
)
from clearbed.warehouse import connect, ensure_app_schema

logger = get_logger("ml.score")


def risk_tier(probability: float) -> str:
    """Map a stuck probability to high, medium, or low."""
    if probability >= 0.6:
        return "high"
    if probability >= 0.3:
        return "medium"
    return "low"


def pseudonym(patient_id: str) -> str:
    """Return a short stable pseudonym. The raw id is not written to the worklist."""
    return hashlib.sha256(patient_id.encode("utf-8")).hexdigest()[:12]


def simulated_day_of_stay(stay_id: str, expected_los: float) -> int:
    """Pick a deterministic day of stay between 1 and the expected length of stay."""
    horizon = max(int(round(expected_los or 4)), 1)
    return 1 + int(unit_interval(f"{stay_id}|day") * horizon)


def score_census(frame: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Score ``frame`` with the three saved models and SHAP reasons."""
    model_dir = settings.resolved_model_dir
    stuck = predict_stuck(frame, model_dir)
    barriers, barrier_prob = predict_barrier(frame, model_dir)
    days = predict_days(frame, model_dir)
    reasons_by_row = explain_frame(frame, model_dir)
    scored_at = datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for position, stay in enumerate(frame.itertuples(index=False)):
        reasons = reasons_by_row[position]
        rows.append(
            {
                "stay_id": str(stay.stay_id),
                "patient_id": pseudonym(str(stay.patient_id)),
                "age_band": str(stay.age_band),
                "condition_group": str(stay.condition_group),
                "payer_type": str(stay.payer_type),
                "day_of_stay": simulated_day_of_stay(
                    str(stay.stay_id), float(stay.expected_los_days)
                ),
                "expected_los": float(stay.expected_los_days),
                "stuck_prob": float(stuck[position]),
                "risk_tier": risk_tier(float(stuck[position])),
                "predicted_barrier": str(barriers[position]),
                "barrier_prob": float(barrier_prob[position]),
                "predicted_avoidable_days": float(days[position]),
                "top_reasons": json.dumps(reasons),
                "scored_at": scored_at,
            }
        )
    return pd.DataFrame(rows)


def write_worklist(scored: pd.DataFrame, settings: Settings) -> dict[str, float]:
    """Replace ``app.worklist`` and append one ``app.daily_summary`` row."""
    projected = float((scored["stuck_prob"] * scored["predicted_avoidable_days"]).sum())
    cost = projected * settings.cost_per_bed_day
    high = int((scored["risk_tier"] == "high").sum())
    con = connect(settings)
    try:
        ensure_app_schema(con)
        con.register("_worklist", scored)
        con.execute("create or replace table app.worklist as select * from _worklist")
        con.unregister("_worklist")
        con.execute(
            """
            insert into app.daily_summary (
                total_census, high_risk_count, projected_avoidable_bed_days,
                estimated_cost, cost_per_bed_day, scored_at
            ) values (?, ?, ?, ?, ?, ?)
            """,
            [int(len(scored)), high, projected, cost, settings.cost_per_bed_day, datetime.now(UTC)],
        )
    finally:
        con.close()
    return {
        "total_census": float(len(scored)),
        "high_risk_count": float(high),
        "projected_avoidable_bed_days": projected,
        "estimated_cost": cost,
    }


def select_census(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    """Return the N most recent admissions."""
    ordered = frame.sort_values("admit_ts", ascending=False)
    return ordered.head(n).sort_values(
        "stuck_prob" if "stuck_prob" in ordered.columns else "admit_ts"
    )


def main() -> None:
    """Score the configured census size and print the daily summary."""
    settings = get_settings()
    frame = load_training_frame(settings)
    census = (
        frame.sort_values("admit_ts", ascending=False)
        .head(settings.census_size)
        .reset_index(drop=True)
    )
    scored = score_census(census, settings)
    summary = write_worklist(scored, settings)
    log_event(logger, "scored census", **{key: round(value, 2) for key, value in summary.items()})
    print(json.dumps(summary, indent=2))
    print(f"app.worklist rows: {len(scored)}")


if __name__ == "__main__":
    main()
