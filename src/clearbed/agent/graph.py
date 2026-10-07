"""LangGraph discharge copilot with a human approval interrupt.

The graph loads a pseudonymized stay, checks cited rules, and routes:

* post-acute placement matches facilities and drafts packets
* payer pending prepares an action that is not a facility referral
* guardianship and home services produce an escalation plan
* no barrier produces a short summary

Facility packets and the payer action stop before ``await_approval``.
Nothing in this module transmits a packet. Status ``sent`` is only a local
record written after a person decides.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from clearbed.agent.llm import build_chat_model, message_text
from clearbed.agent.tools import (
    ReferralStatus,
    ReferralUpdate,
    build_rule_findings,
    draft_referral_packet,
    get_patient_context,
    hospital_coordinates,
    match_facilities,
    update_referral_status,
)
from clearbed.config import Settings, get_settings
from clearbed.logging import get_logger, log_event
from clearbed.warehouse import audit, connect, ensure_app_schema

logger = get_logger("agent.graph")

ACTION_CCN = "ACTION"
DecisionName = Literal["approve", "reject"]

_ACTIVE: ContextVar[Settings | None] = ContextVar("clearbed_active_settings", default=None)
_COMPILED: dict[str, Any] = {}


class AgentState(TypedDict, total=False):
    """Checkpointed copilot state. Values are JSON-friendly."""

    stay_id: str
    run_id: str
    patient_context: dict[str, Any]
    barrier: str
    plan: str
    candidate_facilities: list[dict[str, Any]]
    rule_findings: list[dict[str, Any]]
    packet_drafts: list[dict[str, Any]]
    pending_approvals: list[dict[str, Any]]
    decisions: list[dict[str, Any]]
    messages: list[str]
    errors: list[str]
    retry_count: int
    summary: str
    hospital_zip: str
    next_actions: list[str]
    guard_retry: bool


def active_settings() -> Settings:
    """Return the settings bound to the current run, or the process defaults."""
    current = _ACTIVE.get()
    return current if current is not None else get_settings()


def clear_graph_cache() -> None:
    """Drop compiled graphs. Tests use this when the checkpoint file changes."""
    _COMPILED.clear()


def _citations(findings: list[dict[str, Any]]) -> str:
    lines = []
    for finding in findings:
        url = finding.get("source_url") or ""
        title = finding.get("source_title") or "source"
        claim = finding.get("claim") or ""
        lines.append(f"- {claim} ({title}: {url})")
    return "\n".join(lines) if lines else "- No rule finding was produced."


def _template_summary(state: AgentState) -> str:
    facilities = state.get("candidate_facilities") or []
    names = ", ".join(str(item.get("facility_name")) for item in facilities[:3]) or "none matched"
    actions = state.get("next_actions") or ["No further action from this route."]
    action_text = " ".join(actions)
    return (
        f"Route {state.get('barrier', 'none')}. Facilities considered: {names}. "
        f"Next: {action_text} "
        "A person must approve before any referral is marked sent."
    )


def _unsupported_asserted(
    packet: dict[str, Any],
    context: dict[str, Any],
    facilities: list[dict[str, Any]],
) -> list[str]:
    """Return asserted strings that are neither patient facts nor the chosen facility."""
    blob = json.dumps(context).lower()
    allowed = {
        str(packet.get("facility_name") or "").lower(),
        str(packet.get("facility_ccn") or "").lower(),
    }
    for facility in facilities:
        allowed.add(str(facility.get("facility_name") or "").lower())
        allowed.add(str(facility.get("ccn") or "").lower())
    missing: list[str] = []
    for fact in packet.get("asserted_facts") or []:
        text = str(fact).strip()
        if not text:
            continue
        lowered = text.lower()
        if lowered in allowed or lowered in blob:
            continue
        missing.append(text)
    return missing


def load_context(state: AgentState) -> dict[str, Any]:
    """Load the pseudonymized stay and the rule-based workflow route."""
    settings = active_settings()
    context = get_patient_context(state["stay_id"], settings)
    log_event(
        logger, "graph loaded context", stay_id=state["stay_id"], route=context.workflow_route
    )
    return {
        "patient_context": context.model_dump(),
        "barrier": context.workflow_route,
        "hospital_zip": settings.hospital_zip,
        "retry_count": int(state.get("retry_count") or 0),
        "errors": list(state.get("errors") or []),
        "decisions": list(state.get("decisions") or []),
        "messages": ["Loaded admission context."],
    }


def rules_check(state: AgentState) -> dict[str, Any]:
    """Attach deterministic rule findings. Each one carries a source URL."""
    findings = build_rule_findings(state.get("patient_context") or {}, active_settings())
    return {
        "rule_findings": [item.model_dump() for item in findings],
        "messages": [f"Checked {len(findings)} cited rule(s)."],
    }


def choose_path(state: AgentState) -> str:
    """Pick the next node from the barrier route."""
    return {
        "post_acute_placement": "match",
        "payer_pending": "payer_plan",
        "guardianship_capacity": "escalation",
        "home_services": "home_plan",
    }.get(state.get("barrier") or "", "summarize")


def match(state: AgentState) -> dict[str, Any]:
    """Rank facilities that pass payer, bed, distance, and capability filters."""
    facilities = match_facilities(state["stay_id"], top_k=8, settings=active_settings())
    payload = [item.model_dump() for item in facilities]
    return {
        "candidate_facilities": payload,
        "plan": "post_acute",
        "messages": [f"Matched {len(payload)} facilities."],
    }


def draft(state: AgentState) -> dict[str, Any]:
    """Draft packets for the top three facilities. This does not send them."""
    settings = active_settings()
    packets = []
    for facility in (state.get("candidate_facilities") or [])[:3]:
        packet = draft_referral_packet(state["stay_id"], str(facility["ccn"]), settings)
        packets.append(packet.model_dump())
    return {
        "packet_drafts": packets,
        "guard_retry": False,
        "messages": [f"Drafted {len(packets)} packet(s)."],
    }


def guard(state: AgentState) -> dict[str, Any]:
    """Reject invented clinical facts and uncited rules. Retry the draft once."""
    context = state.get("patient_context") or {}
    facilities = state.get("candidate_facilities") or []
    problems: list[str] = []
    for packet in state.get("packet_drafts") or []:
        for fact in _unsupported_asserted(packet, context, facilities):
            problems.append(f"Unsupported fact in {packet.get('facility_ccn')}: {fact}")
    for finding in state.get("rule_findings") or []:
        if not str(finding.get("source_url") or "").strip():
            problems.append("Rule finding missing source_url.")
    retry_count = int(state.get("retry_count") or 0)
    if problems and retry_count < 1:
        return {
            "guard_retry": True,
            "retry_count": retry_count + 1,
            "errors": list(state.get("errors") or []) + ["Guard asked for one redraft."],
            "messages": ["Guard requested a redraft."],
        }
    errors = list(state.get("errors") or [])
    if problems:
        errors.extend(problems)
        errors.append("Guard failed open after one retry. A person still must approve.")
    return {"guard_retry": False, "errors": errors, "messages": ["Guard finished."]}


def after_guard(state: AgentState) -> str:
    """Redraft once, otherwise wait for approval when a packet exists."""
    if state.get("guard_retry"):
        return "draft"
    if state.get("packet_drafts"):
        return "prepare_approval"
    return "summarize"


def prepare_approval(state: AgentState) -> dict[str, Any]:
    """List facility packets that are waiting for a person."""
    pending = [
        {
            "facility_ccn": packet["facility_ccn"],
            "facility_name": packet.get("facility_name") or packet["facility_ccn"],
            "kind": "facility",
        }
        for packet in state.get("packet_drafts") or []
    ]
    return {
        "pending_approvals": pending,
        "next_actions": [
            "Review each draft, fill every [NEEDS INPUT] item, then approve or reject.",
            "Approving records the referral as sent. It does not transmit the packet.",
        ],
    }


def payer_plan(state: AgentState) -> dict[str, Any]:
    """Payer work is an action item, not a facility referral."""
    return {
        "plan": "payer",
        "candidate_facilities": [],
        "packet_drafts": [],
        "pending_approvals": [
            {
                "facility_ccn": ACTION_CCN,
                "facility_name": "Payer action (not a facility)",
                "kind": "action",
            }
        ],
        "next_actions": [
            "Confirm the payer, member id, and whether a decision is pending. Member id is [NEEDS INPUT].",
            "Do not send a nursing-facility referral while coverage is unresolved.",
            "Record the authorization or state Medicaid pending status before placement calls. "
            "For this hospital, state Medicaid is MassHealth.",
        ],
        "messages": ["Prepared a payer action for approval."],
    }


def escalation(state: AgentState) -> dict[str, Any]:
    """Guardianship route: proxy first, then social work. No referral is drafted."""
    return {
        "plan": "guardianship",
        "candidate_facilities": [],
        "packet_drafts": [],
        "pending_approvals": [],
        "next_actions": [
            "Look for an existing health care proxy or invoked durable power of attorney before anyone mentions guardianship.",
            "If none exists, escalate to social work and hospital counsel. Guardianship is a court process.",
            "Do not draft a nursing-facility packet from this route.",
        ],
        "messages": ["Prepared a guardianship escalation. No facility packet."],
    }


def home_plan(state: AgentState) -> dict[str, Any]:
    """Home-services route. No skilled-nursing packet is drafted."""
    return {
        "plan": "home_services",
        "candidate_facilities": [],
        "packet_drafts": [],
        "pending_approvals": [],
        "next_actions": [
            "Confirm a homebound finding and a skilled need before ordering home health.",
            "Personal care is a separate state Medicaid path. In Massachusetts that path is MassHealth. "
            "Do not mix it into a SNF referral.",
            "Agency and start-of-care date are [NEEDS INPUT].",
        ],
        "messages": ["Prepared a home-services plan. No facility packet."],
    }


def await_approval(state: AgentState) -> dict[str, Any]:
    """Resume point. Decisions are already on the state when this node runs."""
    count = len(state.get("decisions") or [])
    return {"messages": [f"Approval step resumed with {count} decision(s)."]}


def apply_decisions(state: AgentState) -> dict[str, Any]:
    """Record each human decision. Repeating the same status does not add an event."""
    settings = active_settings()
    names = {
        str(item.get("facility_ccn")): str(item.get("facility_name") or "")
        for item in state.get("pending_approvals") or []
    }
    for decision in state.get("decisions") or []:
        approved = decision.get("decision") == "approve"
        recorded: ReferralStatus = "sent" if approved else "declined"
        update_referral_status(
            ReferralUpdate(
                stay_id=state["stay_id"],
                facility_ccn=str(decision.get("facility_ccn")),
                facility_name=str(
                    decision.get("facility_name")
                    or names.get(str(decision.get("facility_ccn")), "")
                ),
                status=recorded,
                note=str(decision.get("note") or ""),
                actor=str(decision.get("actor") or "case_manager"),
                run_id=str(state.get("run_id") or ""),
            ),
            settings,
        )
    return {"messages": ["Recorded approval decisions."]}


def summarize(state: AgentState) -> dict[str, Any]:
    """Write a short summary. Citations are appended from the rule findings."""
    settings = active_settings()
    findings = state.get("rule_findings") or []
    prompt = (
        "Summarize this discharge plan in four sentences. Use only the facts below. "
        "Do not add diagnoses, medications, or coverage approvals that are not listed. "
        "Do not say a referral was sent.\n\n"
        f"Barrier: {state.get('barrier')}\n"
        f"Next actions: {state.get('next_actions')}\n"
        f"Facilities: {[item.get('facility_name') for item in state.get('candidate_facilities') or []]}\n"
        f"Cited findings:\n{_citations(findings)}\n"
    )
    errors = list(state.get("errors") or [])
    try:
        model = build_chat_model(settings)
        text = message_text(model.invoke([HumanMessage(content=prompt)])).strip()
    except Exception:  # noqa: BLE001 — a down model must fall back to the template
        errors.append("Summary model unavailable. Used the template.")
        text = _template_summary(state)
    if not text:
        text = _template_summary(state)
    summary = text + "\n\nCitations:\n" + _citations(findings)
    return {"summary": summary, "errors": errors, "messages": ["Summary ready."]}


def build_graph() -> StateGraph:
    """Return an uncompiled graph. Compilation attaches the SQLite checkpointer."""
    graph: StateGraph = StateGraph(AgentState)
    graph.add_node("load_context", load_context)
    graph.add_node("rules_check", rules_check)
    graph.add_node("match", match)
    graph.add_node("draft", draft)
    graph.add_node("guard", guard)
    graph.add_node("prepare_approval", prepare_approval)
    graph.add_node("payer_plan", payer_plan)
    graph.add_node("escalation", escalation)
    graph.add_node("home_plan", home_plan)
    graph.add_node("await_approval", await_approval)
    graph.add_node("apply_decisions", apply_decisions)
    graph.add_node("summarize", summarize)
    graph.set_entry_point("load_context")
    graph.add_edge("load_context", "rules_check")
    graph.add_conditional_edges(
        "rules_check",
        choose_path,
        ["match", "payer_plan", "escalation", "home_plan", "summarize"],
    )
    graph.add_edge("match", "draft")
    graph.add_edge("draft", "guard")
    graph.add_conditional_edges("guard", after_guard, ["draft", "prepare_approval", "summarize"])
    graph.add_edge("prepare_approval", "await_approval")
    graph.add_edge("payer_plan", "await_approval")
    graph.add_edge("await_approval", "apply_decisions")
    graph.add_edge("apply_decisions", "summarize")
    graph.add_edge("escalation", "summarize")
    graph.add_edge("home_plan", "summarize")
    graph.add_edge("summarize", END)
    return graph


def get_graph(settings: Settings | None = None) -> Any:
    """Compile the graph with a SQLite checkpointer, cached per file path."""
    settings = settings or active_settings()
    path = settings.resolved_checkpoint_path
    key = str(path)
    compiled = _COMPILED.get(key)
    if compiled is not None:
        return compiled
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(connection)
    saver.setup()
    compiled = build_graph().compile(checkpointer=saver, interrupt_before=["await_approval"])
    _COMPILED[key] = compiled
    return compiled


def _config(run_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": run_id}}


def _status_for(graph: Any, run_id: str) -> str:
    snapshot = graph.get_state(_config(run_id))
    if snapshot.next:
        return "awaiting_approval"
    if not snapshot.values:
        return "missing"
    return "complete"


def public_view(state: dict[str, Any], *, status: str) -> dict[str, Any]:
    """Shape a checkpoint for the API. Facility coordinates stay so the map can plot them."""
    settings = active_settings()
    latitude, longitude = hospital_coordinates(
        str(state.get("hospital_zip") or settings.hospital_zip)
    )
    return {
        "run_id": state.get("run_id"),
        "stay_id": state.get("stay_id"),
        "status": status,
        "barrier": state.get("barrier"),
        "plan": state.get("plan"),
        "patient_context": state.get("patient_context") or {},
        "rule_findings": state.get("rule_findings") or [],
        "facilities": state.get("candidate_facilities") or [],
        "packets": state.get("packet_drafts") or [],
        "pending_approvals": state.get("pending_approvals") or [],
        "decisions": state.get("decisions") or [],
        "next_actions": state.get("next_actions") or [],
        "summary": state.get("summary") or "",
        "errors": state.get("errors") or [],
        "hospital": {
            "zip": settings.hospital_zip,
            "latitude": latitude,
            "longitude": longitude,
            "label": "Hospital",
        },
        "capability_note": (
            "Dialysis, trach/vent, behavioral, bariatric, and response hours are synthetic "
            "seeded profiles, not CMS Care Compare fields."
        ),
    }


def persist_run(view: dict[str, Any], settings: Settings) -> None:
    """Upsert the public run view. The JSON does not include a direct patient identifier."""
    con = connect(settings)
    try:
        ensure_app_schema(con)
        now = datetime.now(UTC)
        payload = json.dumps(view, default=str)
        existing = con.execute(
            "select run_id from app.agent_runs where run_id = ?",
            [view.get("run_id")],
        ).fetchone()
        if existing:
            con.execute(
                "update app.agent_runs set status = ?, state_json = ?, updated_at = ? where run_id = ?",
                [view.get("status"), payload, now, view.get("run_id")],
            )
        else:
            con.execute(
                """
                insert into app.agent_runs (run_id, stay_id, status, state_json, created_at, updated_at)
                values (?, ?, ?, ?, ?, ?)
                """,
                [view.get("run_id"), view.get("stay_id"), view.get("status"), payload, now, now],
            )
    finally:
        con.close()


def _view_from_graph(graph: Any, run_id: str) -> dict[str, Any]:
    snapshot = graph.get_state(_config(run_id))
    if not snapshot.values:
        raise KeyError(f"Run {run_id} was not found")
    status = "awaiting_approval" if snapshot.next else "complete"
    return public_view(dict(snapshot.values), status=status)


def start_run(stay_id: str, settings: Settings | None = None) -> dict[str, Any]:
    """Run until the approval interrupt or a terminal summary."""
    settings = settings or get_settings()
    token = _ACTIVE.set(settings)
    try:
        run_id = str(uuid.uuid4())
        graph = get_graph(settings)
        graph.invoke(
            {
                "stay_id": stay_id,
                "run_id": run_id,
                "retry_count": 0,
                "errors": [],
                "decisions": [],
                "messages": [],
            },
            _config(run_id),
        )
        view = _view_from_graph(graph, run_id)
        persist_run(view, settings)
        log_event(
            logger, "started agent run", stay_id=stay_id, run_id=run_id, status=view["status"]
        )
        return view
    finally:
        _ACTIVE.reset(token)


def get_run(run_id: str, settings: Settings | None = None) -> dict[str, Any]:
    """Return the latest public view for a run."""
    settings = settings or get_settings()
    token = _ACTIVE.set(settings)
    try:
        view = _view_from_graph(get_graph(settings), run_id)
        return view
    finally:
        _ACTIVE.reset(token)


def decide(
    run_id: str,
    *,
    facility_ccn: str,
    decision: DecisionName,
    note: str = "",
    actor: str = "case_manager",
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Record one approval immediately, and resume the graph when every item is decided.

    The referral row is written before the graph resumes so the worklist shows
    ``sent`` on the first click. ``update_referral_status`` is idempotent, so the
    resume does not create a second event.
    """
    settings = settings or get_settings()
    token = _ACTIVE.set(settings)
    try:
        graph = get_graph(settings)
        snapshot = graph.get_state(_config(run_id))
        if not snapshot.values:
            raise KeyError(f"Run {run_id} was not found")
        state = dict(snapshot.values)
        pending = list(state.get("pending_approvals") or [])
        known = {str(item.get("facility_ccn")) for item in pending}
        if facility_ccn not in known:
            raise ValueError(f"{facility_ccn} is not awaiting approval on this run")
        decisions = [
            item
            for item in list(state.get("decisions") or [])
            if item.get("facility_ccn") != facility_ccn
        ]
        facility_name = next(
            (
                str(item.get("facility_name") or "")
                for item in pending
                if item.get("facility_ccn") == facility_ccn
            ),
            "",
        )
        decisions.append(
            {
                "facility_ccn": facility_ccn,
                "facility_name": facility_name,
                "decision": decision,
                "note": note,
                "actor": actor,
            }
        )
        status: ReferralStatus = "sent" if decision == "approve" else "declined"
        update_referral_status(
            ReferralUpdate(
                stay_id=str(state["stay_id"]),
                facility_ccn=facility_ccn,
                facility_name=facility_name,
                status=status,
                note=note,
                actor=actor,
                run_id=run_id,
            ),
            settings,
        )
        con = connect(settings)
        try:
            audit(
                con,
                actor=actor,
                action=f"approval_{decision}",
                entity="agent_run",
                entity_id=run_id,
                detail=json.dumps(
                    {
                        "stay_id": state.get("stay_id"),
                        "facility_ccn": facility_ccn,
                        "status": status,
                    }
                ),
            )
        finally:
            con.close()
        graph.update_state(_config(run_id), {"decisions": decisions})
        decided = {str(item.get("facility_ccn")) for item in decisions}
        still_waiting = bool(graph.get_state(_config(run_id)).next)
        if still_waiting and known and known <= decided:
            graph.invoke(None, _config(run_id))
        view = _view_from_graph(graph, run_id)
        persist_run(view, settings)
        return view
    finally:
        _ACTIVE.reset(token)
