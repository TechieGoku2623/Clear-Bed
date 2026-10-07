"""Tools the discharge copilot can call.

Each function has a pydantic input/output shape and a LangChain tool wrapper.
Referral status changes that mean "sent" happen only after a person approves.
Nothing in this module transmits a packet to a facility.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from clearbed.config import Settings, get_settings
from clearbed.features.labeling import route_barrier
from clearbed.logging import get_logger, log_event
from clearbed.rag.ingest_kb import catalog
from clearbed.rag.retriever import retrieve, sanitize_excerpt
from clearbed.warehouse import audit, connect, ensure_app_schema

logger = get_logger("agent.tools")

ReferralStatus = Literal["pending_approval", "sent", "accepted", "declined", "no_response"]


class PatientContext(BaseModel):
    """What a case manager may see. No direct identifiers."""

    stay_id: str
    patient_pseudo_id: str
    age_band: str
    age_at_admit: int
    condition_group: str
    condition_descriptions: list[str] = Field(default_factory=list)
    payer_type: str
    day_of_stay: int
    expected_los: float
    stuck_prob: float
    risk_tier: str
    predicted_barrier: str
    workflow_route: str
    top_reasons: list[str]
    needs_dialysis: bool = False
    needs_trach_vent: bool = False
    needs_behavioral: bool = False
    needs_bariatric: bool = False
    medications: list[str] = Field(default_factory=list)
    has_pt_eval: bool = False
    has_ot_eval: bool = False
    has_pasrr: bool = False
    code_status: str | None = None
    flag_dementia: int = 0
    flag_chf: int = 0
    flag_copd: int = 0
    flag_home_o2: int = 0
    lives_alone_proxy: int = 0
    medicaid_pending: int = 0


class FacilityScore(BaseModel):
    """One ranked facility and the pieces of its score."""

    ccn: str
    facility_name: str
    city: str
    state: str = ""
    zip: str
    distance_miles: float
    overall_rating: float | None
    est_open_beds: int
    typical_response_hours: float | None
    accepts_medicaid: bool
    score: float
    distance_score: float
    rating_score: float
    open_beds_score: float
    response_score: float
    latitude: float | None = None
    longitude: float | None = None


class RuleFinding(BaseModel):
    """A rule statement that must carry a citation."""

    claim: str
    source_url: str
    source_title: str
    deterministic: bool = True


class PacketDraft(BaseModel):
    """A referral draft that may contain only facts from the context."""

    stay_id: str
    facility_ccn: str
    facility_name: str
    markdown: str
    missing_items: list[str]
    asserted_facts: list[str]


class ReferralUpdate(BaseModel):
    """Status change for one facility. ``sent`` requires a prior human approval."""

    stay_id: str
    facility_ccn: str
    status: ReferralStatus
    note: str = ""
    actor: str = "case_manager"
    run_id: str = ""
    facility_name: str = ""


class AvoidableSummary(BaseModel):
    """Leadership totals. Cost uses the configured assumption."""

    total_census: int
    high_risk_count: int
    projected_avoidable_bed_days: float
    estimated_cost: float
    cost_per_bed_day: float
    cost_note: str
    scored_at: str | None = None


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles."""
    radius = 3958.7613
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


# Centroids used when the postal geocoder has no network or no hit.
# 02118 is the Boston Medical Center ZIP configured for this demo.
_ZIP_FALLBACK: dict[str, tuple[float, float]] = {
    "02118": (42.3366, -71.0728),
    "02115": (42.3429, -71.0925),
    "02215": (42.3472, -71.1027),
}


def hospital_coordinates(zip_code: str) -> tuple[float, float]:
    """Return the ZIP centroid for the configured hospital."""
    try:
        import pgeocode

        hit = pgeocode.Nominatim("us").query_postal_code(zip_code)
        latitude = float(hit.latitude)
        longitude = float(hit.longitude)
        if math.isnan(latitude) or math.isnan(longitude):
            raise ValueError(f"No centroid for hospital ZIP {zip_code}")
        return latitude, longitude
    except Exception:  # noqa: BLE001 — geocoder failures fall back to a known hospital ZIP
        fallback = _ZIP_FALLBACK.get(zip_code)
        if fallback is None:
            raise
        return fallback


def accepts_payer(facility: dict[str, Any], payer_type: str) -> bool:
    """Return whether the facility's CMS provider type covers ``payer_type``."""
    provider = str(facility.get("provider_type") or "").lower()
    medicare = "medicare" in provider
    medicaid = bool(facility.get("accepts_medicaid")) or "medicaid" in provider
    if payer_type == "medicare":
        return medicare
    if payer_type in {"medicaid", "dual"}:
        return medicaid
    if payer_type == "commercial":
        return True
    return False


def hard_filter_reasons(
    facility: dict[str, Any],
    *,
    payer_type: str,
    needs: dict[str, bool],
    distance_miles: float | None,
    max_distance_miles: float,
) -> list[str]:
    """Return why a facility is excluded. An empty list means it passes."""
    reasons: list[str] = []
    if int(facility.get("est_open_beds") or 0) <= 0:
        reasons.append("no open beds")
    if not accepts_payer(facility, payer_type):
        reasons.append("payer not accepted")
    if needs.get("needs_dialysis") and not _flag(facility.get("accepts_dialysis")):
        reasons.append("dialysis need not met")
    if needs.get("needs_trach_vent") and not _flag(facility.get("accepts_trach_vent")):
        reasons.append("trach/vent need not met")
    if needs.get("needs_behavioral") and not _flag(facility.get("accepts_behavioral")):
        reasons.append("behavioral need not met")
    if needs.get("needs_bariatric") and not _flag(facility.get("accepts_bariatric")):
        reasons.append("bariatric need not met")
    if distance_miles is not None and distance_miles > max_distance_miles:
        reasons.append("beyond max distance")
    return reasons


def _flag(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes"}
    return bool(value)


def _needs(context: PatientContext) -> dict[str, bool]:
    return {
        "needs_dialysis": context.needs_dialysis,
        "needs_trach_vent": context.needs_trach_vent,
        "needs_behavioral": context.needs_behavioral,
        "needs_bariatric": context.needs_bariatric,
    }


def _texts(rows: list[tuple[Any, ...]]) -> list[str]:
    return [str(row[0]) for row in rows if row and row[0]]


def get_patient_context(stay_id: str, settings: Settings | None = None) -> PatientContext:
    """Load a pseudonymized admission context for one stay."""
    settings = settings or get_settings()
    con = connect(settings, read_only=True)
    try:
        row = con.execute(
            """
            select
                w.stay_id, w.patient_id as pseudo_id, w.age_band, w.condition_group, w.payer_type,
                w.day_of_stay, w.expected_los, w.stuck_prob, w.risk_tier, w.predicted_barrier,
                w.top_reasons, f.patient_id as source_patient_id, f.age_at_admit, f.admit_ts,
                f.flag_dementia, f.flag_chf, f.flag_copd, f.flag_home_o2, f.flag_obesity,
                f.flag_behavioral, f.flag_ckd_dialysis, f.lives_alone_proxy
            from app.worklist as w
            inner join marts.feat_admission_snapshot as f using (stay_id)
            where w.stay_id = ?
            """,
            [stay_id],
        ).fetchone()
        if row is None:
            raise KeyError(f"Stay {stay_id} is not on the worklist")
        columns = [
            "stay_id",
            "pseudo_id",
            "age_band",
            "condition_group",
            "payer_type",
            "day_of_stay",
            "expected_los",
            "stuck_prob",
            "risk_tier",
            "predicted_barrier",
            "top_reasons",
            "source_patient_id",
            "age_at_admit",
            "admit_ts",
            "flag_dementia",
            "flag_chf",
            "flag_copd",
            "flag_home_o2",
            "flag_obesity",
            "flag_behavioral",
            "flag_ckd_dialysis",
            "lives_alone_proxy",
        ]
        record = dict(zip(columns, row, strict=True))
        patient_id = str(record["source_patient_id"])
        admit = record["admit_ts"]
        conditions = _texts(
            con.execute(
                """
                select distinct description from staging.stg_conditions
                where patient_id = ?
                  and (start_ts is null or start_ts <= ?)
                  and (stop_ts is null or stop_ts >= ?)
                limit 12
                """,
                [patient_id, admit, admit],
            ).fetchall()
        )
        medications = _texts(
            con.execute(
                """
                select distinct description from staging.stg_medications
                where patient_id = ?
                  and (start_ts is null or start_ts <= ?)
                  and (stop_ts is null or stop_ts >= ?)
                limit 25
                """,
                [patient_id, admit, admit],
            ).fetchall()
        )
        procedures = _texts(
            con.execute(
                """
                select distinct description from staging.stg_procedures
                where patient_id = ? and start_ts <= ? + interval 3 day
                limit 25
                """,
                [patient_id, admit],
            ).fetchall()
        )
    finally:
        con.close()
    blob = " ".join(conditions + procedures).lower()
    reasons_raw = json.loads(record["top_reasons"] or "[]")
    reason_text = [
        f"{item.get('label', item)} ({item.get('direction', '')})".strip()
        if isinstance(item, dict)
        else str(item)
        for item in reasons_raw
    ]
    features = {
        "age_at_admit": int(record["age_at_admit"] or 0),
        "condition_group": record["condition_group"],
        "payer_type": record["payer_type"],
        "flag_dementia": int(record["flag_dementia"] or 0),
        "lives_alone_proxy": int(record["lives_alone_proxy"] or 0),
        "flag_chf": int(record["flag_chf"] or 0),
        "flag_copd": int(record["flag_copd"] or 0),
        "flag_home_o2": int(record["flag_home_o2"] or 0),
        "predicted_barrier": record["predicted_barrier"],
    }
    log_event(logger, "loaded patient context", stay_id=stay_id)
    return PatientContext(
        stay_id=stay_id,
        patient_pseudo_id=str(record["pseudo_id"]),
        age_band=str(record["age_band"]),
        age_at_admit=int(record["age_at_admit"] or 0),
        condition_group=str(record["condition_group"]),
        condition_descriptions=conditions,
        payer_type=str(record["payer_type"]),
        day_of_stay=int(record["day_of_stay"]),
        expected_los=float(record["expected_los"] or 0),
        stuck_prob=float(record["stuck_prob"] or 0),
        risk_tier=str(record["risk_tier"]),
        predicted_barrier=str(record["predicted_barrier"]),
        workflow_route=route_barrier(features),
        top_reasons=reason_text[:5],
        needs_dialysis="dialysis" in blob or "hemodialysis" in blob,
        needs_trach_vent="trache" in blob or "ventilat" in blob,
        needs_behavioral=bool(int(record["flag_behavioral"] or 0)),
        needs_bariatric=bool(int(record["flag_obesity"] or 0)),
        medications=medications,
        has_pt_eval="physical therapy" in blob,
        has_ot_eval="occupational therapy" in blob,
        has_pasrr="pasrr" in blob,
        code_status=None,
        flag_dementia=int(record["flag_dementia"] or 0),
        flag_chf=int(record["flag_chf"] or 0),
        flag_copd=int(record["flag_copd"] or 0),
        flag_home_o2=int(record["flag_home_o2"] or 0),
        lives_alone_proxy=int(record["lives_alone_proxy"] or 0),
    )


def build_rule_findings(
    context: PatientContext | dict[str, Any], settings: Settings | None = None
) -> list[RuleFinding]:
    """Deterministic rule checks. Every claim carries a source URL."""
    settings = settings or get_settings()
    docs = catalog(settings.resolved_knowledge_dir)
    data = context.model_dump() if isinstance(context, PatientContext) else context
    payer = str(data.get("payer_type") or "")
    day = int(data.get("day_of_stay") or 0)
    route = str(data.get("workflow_route") or data.get("predicted_barrier") or "")
    findings: list[RuleFinding] = []

    def add(doc_id: str, claim: str) -> None:
        meta = docs.get(doc_id, {})
        findings.append(
            RuleFinding(
                claim=claim,
                source_url=meta.get("source_url", ""),
                source_title=meta.get("title", doc_id),
                deterministic=True,
            )
        )

    if payer == "medicare":
        if day < 3:
            add(
                "medicare_snf_coverage",
                f"3-day rule not met: qualifying inpatient days so far are {day}. "
                "Observation days do not count toward the Medicare SNF stay.",
            )
        else:
            add(
                "medicare_snf_coverage",
                f"3-day inpatient count appears met based on day of stay {day}. "
                "Skilled need still has to be documented. Observation days do not count.",
            )
    if payer in {"none", "medicaid"} or int(data.get("medicaid_pending") or 0):
        add(
            "masshealth_ltc_basics",
            "Payer is unresolved or Medicaid. State Medicaid long-term-care eligibility can stay "
            "pending and block placement until a decision is documented. "
            "For this Massachusetts hospital, that agency is MassHealth.",
        )
    if route == "post_acute_placement":
        add(
            "pasrr_screening",
            "PASRR Level I screening is required before nursing facility admission.",
        )
    if route == "guardianship_capacity":
        add(
            "guardianship_ma_basics",
            "Confirm whether a health care proxy already exists before anyone discusses guardianship. "
            "Guardianship is a court process. This citation is Massachusetts law, where the demo hospital sits. "
            "Other states use their own proxy and guardianship rules.",
        )
    if route == "home_services":
        add(
            "home_services_options",
            "Home health needs a homebound finding and a skilled need. "
            "Personal care is a separate state Medicaid path. In Massachusetts that path is MassHealth.",
        )
    return findings


def score_breakdown(
    distance_miles: float,
    rating: float | None,
    open_beds: int,
    response_hours: float | None,
    max_distance: float,
) -> dict[str, float]:
    """Return the weighted score and each component on a 0–1 scale."""
    distance_score = max(0.0, 1.0 - distance_miles / max_distance) if max_distance else 0.0
    rating_score = (float(rating) / 5.0) if rating else 0.0
    open_beds_score = min(max(open_beds, 0) / 20.0, 1.0)
    response_score = max(0.0, 1.0 - float(response_hours or 72) / 72.0)
    total = (
        0.35 * distance_score + 0.25 * rating_score + 0.20 * open_beds_score + 0.20 * response_score
    )
    return {
        "distance_score": round(distance_score, 4),
        "rating_score": round(rating_score, 4),
        "open_beds_score": round(open_beds_score, 4),
        "response_score": round(response_score, 4),
        "score": round(total, 4),
    }


def match_facilities(
    stay_id: str,
    *,
    max_distance_miles: float = 25,
    top_k: int = 8,
    settings: Settings | None = None,
) -> list[FacilityScore]:
    """Rank United States SNFs that pass payer, bed, distance, and capability filters."""
    settings = settings or get_settings()
    context = get_patient_context(stay_id, settings)
    origin = hospital_coordinates(settings.hospital_zip)
    con = connect(settings, read_only=True)
    try:
        frame_rows = con.execute("select * from staging.stg_snf").df().to_dict(orient="records")
    finally:
        con.close()
    ranked: list[FacilityScore] = []
    for facility in frame_rows:
        if facility.get("latitude") is None or facility.get("longitude") is None:
            continue
        distance = haversine_miles(
            origin[0], origin[1], float(facility["latitude"]), float(facility["longitude"])
        )
        if hard_filter_reasons(
            facility,
            payer_type=context.payer_type,
            needs=_needs(context),
            distance_miles=distance,
            max_distance_miles=max_distance_miles,
        ):
            continue
        parts = score_breakdown(
            distance,
            None if facility.get("overall_rating") is None else float(facility["overall_rating"]),
            int(facility.get("est_open_beds") or 0),
            None
            if facility.get("typical_response_hours") is None
            else float(facility["typical_response_hours"]),
            max_distance_miles,
        )
        ranked.append(
            FacilityScore(
                ccn=str(facility["ccn"]),
                facility_name=str(facility["facility_name"]),
                city=str(facility.get("city") or ""),
                state=str(facility.get("state") or ""),
                zip=str(facility.get("zip") or ""),
                distance_miles=round(distance, 2),
                overall_rating=None
                if facility.get("overall_rating") is None
                else float(facility["overall_rating"]),
                est_open_beds=int(facility.get("est_open_beds") or 0),
                typical_response_hours=None
                if facility.get("typical_response_hours") is None
                else float(facility["typical_response_hours"]),
                accepts_medicaid=bool(facility.get("accepts_medicaid")),
                latitude=float(facility["latitude"]),
                longitude=float(facility["longitude"]),
                **parts,
            )
        )
    ranked.sort(key=lambda item: item.score, reverse=True)
    log_event(logger, "matched facilities", stay_id=stay_id, returned=min(top_k, len(ranked)))
    return ranked[:top_k]


def check_payer_rules(
    stay_id: str, question: str, settings: Settings | None = None
) -> dict[str, Any]:
    """Answer from deterministic checks plus retrieved chunks. Never from model memory alone."""
    settings = settings or get_settings()
    context = get_patient_context(stay_id, settings)
    findings = build_rule_findings(context, settings)
    chunks = retrieve(question, k=5, settings=settings)
    if not findings and not chunks:
        return {
            "answer": "insufficient information",
            "citations": [],
            "findings": [],
            "confidence": "insufficient",
        }
    lines = [finding.claim for finding in findings]
    citations = [
        {
            "claim": finding.claim,
            "source_url": finding.source_url,
            "source_title": finding.source_title,
        }
        for finding in findings
    ]
    for chunk in chunks:
        excerpt = sanitize_excerpt(chunk["text"])
        if not excerpt:
            continue
        lines.append(f"Excerpt from {chunk['title']}: {excerpt[:400]}")
        citations.append(
            {
                "claim": chunk["title"],
                "source_url": chunk["source_url"],
                "source_title": chunk["title"],
            }
        )
    return {
        "answer": "\n".join(lines),
        "citations": citations,
        "findings": [finding.model_dump() for finding in findings],
        "confidence": "grounded",
    }


def draft_referral_packet(
    stay_id: str, facility_ccn: str, settings: Settings | None = None
) -> PacketDraft:
    """Draft a packet from structured data. Unknowns are marked ``[NEEDS INPUT]``."""
    settings = settings or get_settings()
    context = get_patient_context(stay_id, settings)
    con = connect(settings, read_only=True)
    try:
        facility = con.execute(
            "select facility_name, city from staging.stg_snf where ccn = ?",
            [facility_ccn],
        ).fetchone()
    finally:
        con.close()
    facility_name = str(facility[0]) if facility else facility_ccn
    city = str(facility[1]) if facility else ""
    missing: list[str] = []
    if not context.has_pt_eval:
        missing.append("PT eval not found")
    if not context.has_ot_eval:
        missing.append("OT eval not found")
    if not context.has_pasrr:
        missing.append("PASRR not documented")
    missing.append("H&P narrative [NEEDS INPUT]")
    if context.code_status is None:
        missing.append("Code status [NEEDS INPUT]")
    missing.append("Insurance member id [NEEDS INPUT]")
    meds = context.medications or ["No medications found in the record [NEEDS INPUT]"]
    conditions = context.condition_descriptions or [context.condition_group]
    asserted = [
        context.age_band,
        str(context.age_at_admit),
        context.condition_group,
        context.payer_type,
        facility_name,
        *conditions,
        *context.medications,
    ]
    needs = [
        f"dialysis: {'yes' if context.needs_dialysis else 'not documented'}",
        f"trach/vent: {'yes' if context.needs_trach_vent else 'not documented'}",
        f"behavioral: {'yes' if context.needs_behavioral else 'not documented'}",
        f"bariatric: {'yes' if context.needs_bariatric else 'not documented'}",
    ]
    markdown = "\n".join(
        [
            f"# Referral draft — {facility_name}",
            "",
            f"Facility CCN: {facility_ccn} ({city})",
            f"Stay: {context.stay_id}",
            f"Patient: {context.patient_pseudo_id}",
            "",
            "## Clinical summary",
            f"Age band {context.age_band} (age at admission {context.age_at_admit}).",
            f"Primary condition group: {context.condition_group}.",
            "Conditions in the record: " + "; ".join(conditions) + ".",
            f"Payer at admission: {context.payer_type}.",
            f"Day of stay {context.day_of_stay} versus expected length of stay {context.expected_los:.1f}.",
            "",
            "## Medications",
            *[f"- {med}" for med in meds],
            "",
            "## Needs",
            *[f"- {item}" for item in needs],
            "",
            "## Missing items",
            *[f"- {item}" for item in missing],
            "",
            "Generated from structured synthetic data. Unknowns are marked [NEEDS INPUT].",
        ]
    )
    return PacketDraft(
        stay_id=stay_id,
        facility_ccn=facility_ccn,
        facility_name=facility_name,
        markdown=markdown,
        missing_items=missing,
        asserted_facts=[fact for fact in asserted if fact],
    )


def update_referral_status(
    update: ReferralUpdate, settings: Settings | None = None
) -> dict[str, str]:
    """Record a referral status. Identical repeats do not add another event."""
    settings = settings or get_settings()
    con = connect(settings)
    try:
        ensure_app_schema(con)
        existing = con.execute(
            "select referral_id, status from app.referrals where stay_id = ? and facility_ccn = ?",
            [update.stay_id, update.facility_ccn],
        ).fetchone()
        now = datetime.now(UTC)
        if existing and existing[1] == update.status:
            return {"referral_id": str(existing[0]), "status": update.status}
        if existing:
            referral_id = str(existing[0])
            con.execute(
                """
                update app.referrals
                set status = ?, note = ?, actor = ?, run_id = ?, updated_at = ?, facility_name = ?
                where referral_id = ?
                """,
                [
                    update.status,
                    update.note,
                    update.actor,
                    update.run_id,
                    now,
                    update.facility_name,
                    referral_id,
                ],
            )
        else:
            referral_id = str(uuid.uuid4())
            con.execute(
                """
                insert into app.referrals (
                    referral_id, stay_id, facility_ccn, facility_name, status, note, actor, run_id, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    referral_id,
                    update.stay_id,
                    update.facility_ccn,
                    update.facility_name,
                    update.status,
                    update.note,
                    update.actor,
                    update.run_id,
                    now,
                    now,
                ],
            )
        con.execute(
            """
            insert into app.referral_events (
                event_id, referral_id, stay_id, facility_ccn, status, note, actor, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                str(uuid.uuid4()),
                referral_id,
                update.stay_id,
                update.facility_ccn,
                update.status,
                update.note,
                update.actor,
                now,
            ],
        )
        audit(
            con,
            actor=update.actor,
            action=f"referral_{update.status}",
            entity="referral",
            entity_id=referral_id,
            detail=json.dumps(
                {
                    "stay_id": update.stay_id,
                    "facility_ccn": update.facility_ccn,
                    "status": update.status,
                }
            ),
        )
    finally:
        con.close()
    log_event(
        logger,
        "updated referral",
        stay_id=update.stay_id,
        facility_ccn=update.facility_ccn,
        status=update.status,
    )
    return {"referral_id": referral_id, "status": update.status}


def get_avoidable_days_summary(settings: Settings | None = None) -> AvoidableSummary:
    """Read the latest daily summary. Cost is the configured assumption."""
    settings = settings or get_settings()
    con = connect(settings)
    try:
        ensure_app_schema(con)
        row = con.execute(
            """
            select total_census, high_risk_count, projected_avoidable_bed_days,
                   estimated_cost, cost_per_bed_day, scored_at
            from app.daily_summary
            order by scored_at desc
            limit 1
            """
        ).fetchone()
    finally:
        con.close()
    note = (
        f"Cost uses an assumed ${settings.cost_per_bed_day:,.0f} per bed-day. "
        "This is not a figure from the hospital finance system."
    )
    if row is None:
        return AvoidableSummary(
            total_census=0,
            high_risk_count=0,
            projected_avoidable_bed_days=0,
            estimated_cost=0,
            cost_per_bed_day=settings.cost_per_bed_day,
            cost_note=note,
        )
    return AvoidableSummary(
        total_census=int(row[0]),
        high_risk_count=int(row[1]),
        projected_avoidable_bed_days=float(row[2]),
        estimated_cost=float(row[3]),
        cost_per_bed_day=float(row[4]),
        cost_note=note,
        scored_at=str(row[5]) if row[5] is not None else None,
    )


def unsupported_facts(
    markdown: str, context: dict[str, Any], forbidden: list[str] | None = None
) -> list[str]:
    """Return phrases in the packet that the context does not support."""
    blob = json.dumps(context).lower()
    hits: list[str] = []
    for phrase in forbidden or []:
        if phrase.lower() in markdown.lower() and phrase.lower() not in blob:
            hits.append(phrase)
    return hits


class _StayInput(BaseModel):
    stay_id: str


class _MatchInput(BaseModel):
    stay_id: str
    max_distance_miles: float = 25
    top_k: int = 8


class _RulesInput(BaseModel):
    stay_id: str
    question: str


class _PacketInput(BaseModel):
    stay_id: str
    facility_ccn: str


def langchain_tools() -> list[StructuredTool]:
    """Wrap the functions as LangChain tools. The graph calls the functions directly."""

    def _context(stay_id: str) -> str:
        return get_patient_context(stay_id).model_dump_json()

    def _match(stay_id: str, max_distance_miles: float = 25, top_k: int = 8) -> str:
        found = match_facilities(stay_id, max_distance_miles=max_distance_miles, top_k=top_k)
        return json.dumps([item.model_dump() for item in found])

    def _rules(stay_id: str, question: str) -> str:
        return json.dumps(check_payer_rules(stay_id, question))

    def _packet(stay_id: str, facility_ccn: str) -> str:
        return draft_referral_packet(stay_id, facility_ccn).model_dump_json()

    def _status(stay_id: str, facility_ccn: str, status: ReferralStatus, note: str = "") -> str:
        update = ReferralUpdate(
            stay_id=stay_id, facility_ccn=facility_ccn, status=status, note=note
        )
        return json.dumps(update_referral_status(update))

    def _summary() -> str:
        return get_avoidable_days_summary().model_dump_json()

    return [
        StructuredTool.from_function(
            func=_context,
            name="get_patient_context",
            description="Pseudonymized stay context.",
            args_schema=_StayInput,
        ),
        StructuredTool.from_function(
            func=_match,
            name="match_facilities",
            description="Rank SNFs with a score breakdown.",
            args_schema=_MatchInput,
        ),
        StructuredTool.from_function(
            func=_rules,
            name="check_payer_rules",
            description="Grounded payer-rule answer with citations.",
            args_schema=_RulesInput,
        ),
        StructuredTool.from_function(
            func=_packet,
            name="draft_referral_packet",
            description="Draft a packet. Does not send it.",
            args_schema=_PacketInput,
        ),
        StructuredTool.from_function(
            func=_status,
            name="update_referral_status",
            description="Record a referral status after human approval.",
            args_schema=ReferralUpdate,
        ),
        StructuredTool.from_function(
            func=_summary,
            name="get_avoidable_days_summary",
            description="Census avoidable-day and cost summary.",
        ),
    ]
