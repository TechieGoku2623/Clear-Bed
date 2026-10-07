"""FastAPI surface for the worklist, copilot, and leadership dashboard.

The UI talks only to this API. Write operations require ``X-API-Key`` and
are appended to ``app.audit_log``. Referral status ``sent`` is a local record
created after a person approves. This service does not contact a facility.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from clearbed.agent.graph import decide, get_run, start_run
from clearbed.agent.tools import get_avoidable_days_summary, get_patient_context
from clearbed.api.schemas import (
    DecisionRequest,
    LeadershipResponse,
    ReferralEvent,
    RunRequest,
    WorklistRow,
)
from clearbed.config import Settings, get_settings
from clearbed.logging import configure_logging, get_logger, log_event
from clearbed.warehouse import audit, connect, ensure_app_schema

logger = get_logger("api")


def _settings() -> Settings:
    return get_settings()


def require_api_key(
    x_api_key: str = Header(default=""),
    settings: Settings = Depends(_settings),
) -> None:
    """Reject missing or wrong demo keys. This is not a production identity system."""
    if not x_api_key or x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")


app = FastAPI(
    title="ClearBed",
    version="0.1.0",
    description="Discharge-barrier worklist and placement copilot. Synthetic patients unless DATA_MODE says otherwise.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8501",
        "http://127.0.0.1:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    configure_logging(get_settings())


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. No API key, no patient data."""
    settings = get_settings()
    return {"status": "ok", "data_mode": settings.data_mode}


@app.get("/about")
def about(_: None = Depends(require_api_key)) -> dict[str, Any]:
    """Model card text and the limits a buyer should see. Does not query the warehouse."""
    settings = get_settings()
    card_path = settings.resolved_model_dir / "model_card.md"
    card = (
        card_path.read_text(encoding="utf-8")
        if card_path.exists()
        else "Run make train to write the model card."
    )
    return {
        "data_mode": settings.data_mode,
        "model_card": card,
        "limitations": [
            "Labels are a synthetic function of admission features. Metrics are not clinical validation.",
            "SNF capability flags and response hours are synthetic and labeled as such.",
            "Knowledge-base rules are drafts. Verify them before operational use.",
            f"Cost uses an assumed ${settings.cost_per_bed_day:,.0f} per bed-day, not a finance-system figure.",
            "Referrals are recorded only after a person approves them. Nothing is auto-sent.",
        ],
    }


def _reasons(raw: str | None) -> list[Any]:
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return [raw]
    return parsed if isinstance(parsed, list) else [parsed]


@app.get("/worklist", response_model=list[WorklistRow])
def worklist(
    tier: str | None = None,
    barrier: str | None = None,
    _: None = Depends(require_api_key),
) -> list[WorklistRow]:
    """Return the scored census, highest stuck probability first."""
    con = connect()
    try:
        ensure_app_schema(con)
        rows = con.execute(
            """
            select stay_id, patient_id, age_band, condition_group, payer_type, day_of_stay,
                   expected_los, stuck_prob, risk_tier, predicted_barrier, predicted_avoidable_days, top_reasons
            from app.worklist
            order by stuck_prob desc
            """
        ).fetchall()
    finally:
        con.close()
    items = [
        WorklistRow(
            stay_id=str(row[0]),
            patient_pseudo_id=str(row[1]),
            age_band=str(row[2]),
            condition_group=str(row[3]),
            payer_type=str(row[4]),
            day_of_stay=int(row[5]),
            expected_los=float(row[6] or 0),
            stuck_prob=float(row[7] or 0),
            risk_tier=str(row[8]),
            predicted_barrier=str(row[9]),
            predicted_avoidable_days=float(row[10] or 0),
            top_reasons=_reasons(row[11]),
        )
        for row in rows
    ]
    if tier:
        items = [item for item in items if item.risk_tier == tier]
    if barrier:
        items = [item for item in items if item.predicted_barrier == barrier]
    return items


@app.get("/patients/{stay_id}")
def patient(stay_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
    """Return the pseudonymized context for one stay."""
    try:
        context = get_patient_context(stay_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface a missing warehouse as 404
        raise HTTPException(status_code=404, detail="Stay is not on the worklist") from exc
    return context.model_dump()


@app.get("/leadership", response_model=LeadershipResponse)
def leadership(_: None = Depends(require_api_key)) -> LeadershipResponse:
    """Census KPIs, a bed-day series, and referral counts that exclude payer-only actions."""
    summary = get_avoidable_days_summary()
    con = connect()
    try:
        ensure_app_schema(con)
        history = con.execute(
            """
            select projected_avoidable_bed_days, estimated_cost, high_risk_count, scored_at
            from app.daily_summary
            order by scored_at
            """
        ).fetchall()
        statuses = con.execute(
            """
            select status from app.referrals
            where facility_ccn <> 'ACTION'
            """
        ).fetchall()
    finally:
        con.close()
    simulated = len(history) < 2
    series: list[dict[str, Any]] = []
    if not history:
        series_note = "No census has been scored yet."
    elif simulated:
        base_days = float(history[-1][0] or 0)
        base_cost = float(history[-1][1] or 0)
        base_high = int(history[-1][2] or 0)
        for day in range(14):
            factor = 0.82 + 0.018 * ((day * 3) % 7)
            series.append(
                {
                    "day": day - 13,
                    "avoidable_bed_days": round(base_days * factor, 2),
                    "estimated_cost": round(base_cost * factor, 2),
                    "high_risk_count": max(0, int(round(base_high * factor))),
                }
            )
        series_note = (
            "Simulated 14-day backcast from a single scored census. "
            "It is not a historical trend from the hospital."
        )
    else:
        for index, row in enumerate(history):
            series.append(
                {
                    "day": index - len(history) + 1,
                    "avoidable_bed_days": float(row[0] or 0),
                    "estimated_cost": float(row[1] or 0),
                    "high_risk_count": int(row[2] or 0),
                    "scored_at": str(row[3]),
                }
            )
        series_note = "Each point is a scored census snapshot."
    counts = Counter(str(row[0]) for row in statuses)
    return LeadershipResponse(
        total_census=summary.total_census,
        high_risk_count=summary.high_risk_count,
        projected_avoidable_bed_days=summary.projected_avoidable_bed_days,
        estimated_cost=summary.estimated_cost,
        cost_per_bed_day=summary.cost_per_bed_day,
        cost_note=summary.cost_note,
        scored_at=summary.scored_at,
        series=series,
        series_note=series_note,
        simulated_backcast=simulated and bool(history),
        referrals_by_status=dict(counts),
    )


@app.post("/plans")
def create_plan(body: RunRequest, _: None = Depends(require_api_key)) -> dict[str, Any]:
    """Run the copilot until it needs a person or finishes a non-referral route."""
    try:
        view = start_run(body.stay_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    con = connect()
    try:
        audit(
            con,
            actor="case_manager",
            action="plan_created",
            entity="agent_run",
            entity_id=str(view.get("run_id")),
            detail=json.dumps({"stay_id": body.stay_id, "status": view.get("status")}),
        )
    finally:
        con.close()
    log_event(logger, "created plan", stay_id=body.stay_id, run_id=view.get("run_id"))
    return view


@app.get("/plans/{run_id}")
def read_plan(run_id: str, _: None = Depends(require_api_key)) -> dict[str, Any]:
    """Return the stored public view for a run."""
    try:
        return get_run(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/plans/{run_id}/decisions")
def post_decision(
    run_id: str,
    body: DecisionRequest,
    _: None = Depends(require_api_key),
) -> dict[str, Any]:
    """Approve or reject one pending item. Approval writes status ``sent`` immediately."""
    try:
        return decide(
            run_id,
            facility_ccn=body.facility_ccn,
            decision=body.decision,
            note=body.note,
            actor=body.actor,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/referrals", response_model=list[ReferralEvent])
def referrals(
    stay_id: str | None = None, _: None = Depends(require_api_key)
) -> list[ReferralEvent]:
    """Timeline of referral status changes, oldest first."""
    con = connect()
    try:
        ensure_app_schema(con)
        if stay_id:
            rows = con.execute(
                """
                select e.referral_id, e.stay_id, e.facility_ccn, r.facility_name, e.status, e.note, e.actor, e.created_at
                from app.referral_events as e
                left join app.referrals as r on e.referral_id = r.referral_id
                where e.stay_id = ?
                order by e.created_at
                """,
                [stay_id],
            ).fetchall()
        else:
            rows = con.execute(
                """
                select e.referral_id, e.stay_id, e.facility_ccn, r.facility_name, e.status, e.note, e.actor, e.created_at
                from app.referral_events as e
                left join app.referrals as r on e.referral_id = r.referral_id
                order by e.created_at
                """
            ).fetchall()
    finally:
        con.close()
    return [
        ReferralEvent(
            referral_id=str(row[0]),
            stay_id=str(row[1]),
            facility_ccn=str(row[2]),
            facility_name=str(row[3] or ""),
            status=str(row[4]),
            note=str(row[5] or ""),
            actor=str(row[6] or ""),
            created_at=str(row[7]) if row[7] is not None else None,
        )
        for row in rows
    ]
