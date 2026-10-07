"""ClearBed case-management and leadership UI.

Every number on screen comes from the API. This file does not open DuckDB.
Approving a packet records it as sent. It does not transmit anything.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests
import streamlit as st

API_BASE = os.environ.get("API_BASE_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "demo-key")

BADGE = "Synthetic patient data — demo."
BANNER = "Synthetic data — demo only"

CSS = """
<style>
    .stApp { background: #f4f7f7; }
    html, body, [class*="css"] { font-size: 17px; }
    .block-container { padding-top: 1.4rem; padding-bottom: 2rem; }
    header[data-testid="stHeader"], footer, #MainMenu { display: none; }
    h1, h2, h3 { color: #16343d; letter-spacing: -0.02em; }
    [data-testid="stSidebar"],
    [data-testid="stSidebarContent"],
    [data-testid="stSidebarUserContent"] {
        background-color: #16343d !important;
    }
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] h2 {
        color: #f4f7f7 !important;
    }
    .kpi {
        background: white;
        border-top: 4px solid #1f6f78;
        border-radius: 8px;
        padding: 14px 16px;
        box-shadow: 0 1px 2px rgba(22, 52, 61, 0.08);
    }
    .kpi .label { color: #5c7176; font-size: 0.85rem; margin: 0; }
    .kpi .value { color: #16343d; font-size: 1.8rem; font-weight: 650; margin: 0; }
    .banner {
        background: #16343d;
        color: white;
        padding: 8px 12px;
        border-radius: 6px;
        font-size: 0.9rem;
        margin-bottom: 12px;
    }
    .demo-badge {
        position: fixed;
        top: 12px;
        right: 16px;
        z-index: 100000;
        background: #1f6f78;
        color: #ffffff;
        padding: 6px 10px;
        border-radius: 6px;
        font-size: 12px;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.25);
    }
    div[data-baseweb="select"] > div {
        background-color: #ffffff !important;
        color: #16343d !important;
    }
    div[data-baseweb="select"] span,
    div[data-baseweb="select"] div {
        color: #16343d !important;
    }
    button[data-testid="stBaseButton-primary"] {
        background-color: #1f6f78 !important;
        color: #ffffff !important;
        border: none !important;
    }
    mark { background: #f6e2a4; padding: 0 3px; }
    .reason { margin: 4px 0; color: #16343d; }
    .gauge {
        background: #d5e2e3;
        border-radius: 999px;
        height: 22px;
        overflow: hidden;
        margin: 8px 0 14px 0;
    }
    .gauge > div { height: 100%; background: #1f6f78; }
    .note { color: #5c7176; font-size: 0.95rem; }
    .demo-card {
        background: white;
        border-left: 4px solid #1f6f78;
        border-radius: 8px;
        padding: 12px 14px;
        margin: 8px 0 16px 0;
    }
    .demo-card strong { color: #16343d; }
</style>
"""


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY}


def api_get(path: str, **params: Any) -> Any:
    """GET a JSON resource. Raises on HTTP errors so the page can show them."""
    response = requests.get(f"{API_BASE}{path}", headers=_headers(), params=params, timeout=120)
    response.raise_for_status()
    return response.json()


def api_post(path: str, payload: dict[str, Any]) -> Any:
    """POST JSON. Used for plan generation and approval."""
    response = requests.post(f"{API_BASE}{path}", headers=_headers(), json=payload, timeout=180)
    response.raise_for_status()
    return response.json()


def _guard() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    st.markdown(f'<div class="demo-badge">{BADGE}</div>', unsafe_allow_html=True)


def _kpi(label: str, value: str) -> None:
    st.markdown(
        f"<div class='kpi'><p class='label'>{label}</p><p class='value'>{value}</p></div>",
        unsafe_allow_html=True,
    )


def _reason_lines(reasons: list[Any]) -> list[str]:
    lines: list[str] = []
    for item in reasons[:5]:
        if isinstance(item, dict):
            label = str(item.get("label") or item.get("feature") or "Factor")
            direction = str(item.get("direction") or "").strip()
            lines.append(f"{label} ({direction})" if direction else label)
        else:
            lines.append(str(item))
    return lines


def page_leadership() -> None:
    """Census KPIs, the cost assumption, and the referral funnel."""
    st.markdown(f'<div class="banner">{BANNER}</div>', unsafe_allow_html=True)
    st.title("Leadership")
    st.caption(
        "Bed-days this hospital is about to lose. The nursing-home catalog covers the United States."
    )
    try:
        data = api_get("/leadership")
    except requests.RequestException as exc:
        st.error(f"API unavailable at {API_BASE}. Start it with `make api`. ({exc})")
        return
    columns = st.columns(4)
    with columns[0]:
        _kpi("Census", f"{data['total_census']}")
    with columns[1]:
        _kpi("High risk", f"{data['high_risk_count']}")
    with columns[2]:
        _kpi("Avoidable bed-days", f"{data['projected_avoidable_bed_days']:.1f}")
    with columns[3]:
        _kpi("Estimated cost", f"${data['estimated_cost']:,.0f}")
    st.markdown(f"<p class='note'>{data['cost_note']}</p>", unsafe_allow_html=True)
    chart_col, funnel_col = st.columns(2)
    with chart_col:
        st.subheader("Avoidable bed-days")
        st.caption(data["series_note"])
        if data["series"]:
            chart_rows = {row["day"]: row["avoidable_bed_days"] for row in data["series"]}
            st.line_chart(chart_rows, height=280)
    with funnel_col:
        st.subheader("Referral funnel")
        st.caption("Facility referrals only. Payer actions are excluded from this count.")
        counts = data.get("referrals_by_status") or {}
        if counts:
            st.bar_chart(counts, height=280)
        else:
            st.info("No facility referrals have been approved or declined yet.")
    counts_by_state = data.get("facilities_by_state") or {}
    if counts_by_state:
        st.subheader("Nursing homes across the United States")
        st.caption(data.get("catalog_note") or "")
        st.bar_chart(counts_by_state, height=280)


def page_worklist() -> None:
    """Ranked census with a tier filter."""
    st.title("Worklist")
    st.caption(
        "Ranked by stuck probability. Flags are computed from admission data, not from day six."
    )
    try:
        rows = api_get("/worklist")
    except requests.RequestException as exc:
        st.error(f"API unavailable at {API_BASE}. ({exc})")
        return
    tiers = ["All"] + sorted({row["risk_tier"] for row in rows})
    barriers = ["All"] + sorted({row["predicted_barrier"] for row in rows})
    left, right = st.columns(2)
    tier = left.selectbox("Risk tier", tiers, index=0)
    barrier = right.selectbox("Predicted barrier", barriers, index=0)
    demo = _placement_demo(rows)
    if demo is not None:
        st.markdown(
            "<div class='demo-card'><strong>Placement demo.</strong> "
            f"{demo['patient_pseudo_id']} · {demo['condition_group']} · {demo['payer_type']} · "
            f"{demo['age_band']} · stuck {demo['stuck_prob']:.0%}. "
            "The High filter on this census is home services and guardianship. "
            "This Medicare stay is the one that matches nursing homes.</div>",
            unsafe_allow_html=True,
        )
        if st.button("Open placement demo", type="primary"):
            st.session_state["stay_id"] = demo["stay_id"]
            st.session_state["goto"] = "Patient"
            st.rerun()
    shown = [
        row
        for row in rows
        if (tier == "All" or row["risk_tier"] == tier)
        and (barrier == "All" or row["predicted_barrier"] == barrier)
    ]
    table = [
        {
            "Patient": row["patient_pseudo_id"],
            "Age band": row["age_band"],
            "Condition": row["condition_group"],
            "Payer": row["payer_type"],
            "Day of stay": row["day_of_stay"],
            "Expected LOS": round(row["expected_los"], 1),
            "Stuck probability": round(row["stuck_prob"], 2),
            "Tier": row["risk_tier"],
            "Barrier": row["predicted_barrier"],
        }
        for row in shown
    ]
    st.dataframe(table, width="stretch", hide_index=True)
    st.caption(f"{len(shown)} stays shown.")
    options = {
        f"{row['patient_pseudo_id']} · {row['condition_group']} · {row['risk_tier']}": row[
            "stay_id"
        ]
        for row in shown
    }
    if not options:
        return
    label = st.selectbox("Open a stay", list(options))
    if st.button("Open patient", type="primary"):
        st.session_state["stay_id"] = options[label]
        st.session_state["goto"] = "Patient"
        st.rerun()


def _placement_demo(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the Medicare post-acute stay a recording should open for the map."""
    candidates = [
        row
        for row in rows
        if row.get("predicted_barrier") == "post_acute_placement"
        and row.get("payer_type") == "medicare"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda row: float(row.get("stuck_prob") or 0), reverse=True)
    return candidates[0]


def _status_for(stay_id: str) -> dict[str, str]:
    try:
        events = api_get("/referrals", stay_id=stay_id)
    except requests.RequestException:
        return {}
    latest: dict[str, str] = {}
    for event in events:
        latest[str(event["facility_ccn"])] = str(event["status"])
    return latest


def page_patient() -> None:
    """Risk, reasons, plan, map, packet, and the approval control."""
    st.title("Patient")
    try:
        rows = api_get("/worklist")
    except requests.RequestException as exc:
        st.error(f"API unavailable at {API_BASE}. ({exc})")
        return
    if not rows:
        st.info("The worklist is empty. Score a census with `make score`.")
        return
    labels = {
        f"{row['patient_pseudo_id']} · {row['condition_group']} · {row['risk_tier']} ({row['stuck_prob']:.0%})": row[
            "stay_id"
        ]
        for row in rows
    }
    current = st.session_state.get("stay_id")
    default_index = 0
    stay_ids = list(labels.values())
    if current in stay_ids:
        default_index = stay_ids.index(current)
    choice = st.selectbox("Stay", list(labels), index=default_index)
    stay_id = labels[choice]
    st.session_state["stay_id"] = stay_id
    try:
        context = api_get(f"/patients/{stay_id}")
    except requests.RequestException as exc:
        st.error(f"Could not load this stay. ({exc})")
        return
    probability = float(context.get("stuck_prob") or 0)
    plan = st.session_state.get(f"plan:{stay_id}")
    left, right = st.columns([1.05, 1])
    with left:
        st.subheader(f"{context.get('risk_tier', '').title()} risk · {probability:.0%}")
        st.markdown(
            f"<div class='gauge'><div style='width:{max(4, int(probability * 100))}%'></div></div>",
            unsafe_allow_html=True,
        )
        st.markdown("**Why this flag**")
        for line in _reason_lines(context.get("top_reasons") or []):
            st.markdown(f"<p class='reason'>{line}</p>", unsafe_allow_html=True)
        alone = "yes" if context.get("lives_alone_proxy") else "no"
        st.caption(
            f"{context.get('age_band')} ({context.get('age_at_admit')}) · "
            f"{context.get('condition_group')} · {context.get('payer_type')} · "
            f"day {context.get('day_of_stay')} vs expected {float(context.get('expected_los') or 0):.1f} · "
            f"route {context.get('workflow_route')} · lives alone {alone}"
        )
        if st.button("Generate plan", type="primary"):
            with st.spinner("Matching facilities and drafting. Nothing is sent."):
                try:
                    plan = api_post("/plans", {"stay_id": stay_id})
                except requests.RequestException as exc:
                    st.error(f"Plan failed. ({exc})")
                    return
            st.session_state[f"plan:{stay_id}"] = plan
            st.rerun()
    with right:
        if plan and (plan.get("facilities") or []):
            _facility_map(plan)
        else:
            st.markdown(f"**Age band** {context.get('age_band')} ({context.get('age_at_admit')})")
            st.markdown(f"**Condition** {context.get('condition_group')}")
            st.markdown(f"**Payer** {context.get('payer_type')}")
            st.markdown(
                f"**Day of stay** {context.get('day_of_stay')} vs expected "
                f"{float(context.get('expected_los') or 0):.1f}"
            )
            st.markdown(f"**Route** {context.get('workflow_route')}")
            st.markdown(f"**Lives alone (synthetic proxy)** {alone}")
    if not plan:
        st.caption("Generate a plan to see the map, the score breakdown, and the draft packet.")
        return
    _render_plan(stay_id, plan)


def _facility_map(plan: dict[str, Any]) -> None:
    """Map of the hospital and ranked United States nursing homes, beside the reasons."""
    facilities = plan.get("facilities") or []
    hospital = plan.get("hospital") or {}
    if hospital.get("latitude") is None or hospital.get("longitude") is None:
        return
    facility_rows = [
        {
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "facility_name": item["facility_name"],
            "score": item["score"],
        }
        for item in facilities
        if item.get("latitude") is not None and item.get("longitude") is not None
    ]
    if not facility_rows:
        return
    payload = json.dumps(
        {
            "hospital": {
                "latitude": float(hospital["latitude"]),
                "longitude": float(hospital["longitude"]),
            },
            "facilities": facility_rows,
        }
    )
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
      <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
      <style>
        html, body, #map {{ margin: 0; padding: 0; height: 340px; width: 100%; background: #f4f7f7; }}
        .leaflet-control-attribution {{ font-size: 10px; }}
      </style>
    </head>
    <body>
      <div id="map"></div>
      <script>
        const data = {payload};
        const map = L.map('map', {{zoomControl: false}}).setView(
          [data.hospital.latitude, data.hospital.longitude], 11
        );
        L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
          maxZoom: 19,
          attribution: '&copy; OpenStreetMap'
        }}).addTo(map);
        L.circleMarker([data.hospital.latitude, data.hospital.longitude], {{
          radius: 9, color: '#ffffff', weight: 2, fillColor: '#16343d', fillOpacity: 1
        }}).addTo(map).bindTooltip('Hospital');
        data.facilities.forEach((facility, index) => {{
          L.circleMarker([facility.latitude, facility.longitude], {{
            radius: index === 0 ? 8 : 6,
            color: '#ffffff',
            weight: 2,
            fillColor: '#1f6f78',
            fillOpacity: 0.95
          }}).addTo(map).bindTooltip(facility.facility_name);
        }});
        setTimeout(() => map.invalidateSize(), 150);
      </script>
    </body>
    </html>
    """
    st.subheader("Facilities")
    top = facilities[0]
    st.caption(
        f"Dark pin is the hospital. Teal pins are ranked United States nursing homes near it. "
        f"Top match: {top.get('facility_name')}."
    )
    map_path = Path("/tmp/clearbed-facility-map.html")
    map_path.write_text(html, encoding="utf-8")
    st.iframe(map_path, height=340)
    note = plan.get("capability_note")
    if note:
        st.caption(str(note))


def _render_plan(stay_id: str, plan: dict[str, Any]) -> None:
    st.subheader("Plan")
    st.markdown(f"**Barrier route:** {plan.get('barrier')}")
    if plan.get("errors"):
        for error in plan["errors"]:
            st.warning(str(error))
    for action in plan.get("next_actions") or []:
        st.markdown(f"- {action}")
    facilities = plan.get("facilities") or []
    if facilities:
        st.subheader("Score breakdown")
        st.dataframe(
            [
                {
                    "Facility": item["facility_name"],
                    "City": item["city"],
                    "State": item.get("state") or "",
                    "Miles": item["distance_miles"],
                    "Rating": item["overall_rating"],
                    "Open beds": item["est_open_beds"],
                    "Response hours": item["typical_response_hours"],
                    "Distance score": item["distance_score"],
                    "Rating score": item["rating_score"],
                    "Open beds score": item["open_beds_score"],
                    "Response score": item["response_score"],
                    "Score": item["score"],
                }
                for item in facilities
            ],
            width="stretch",
            hide_index=True,
        )
    findings = plan.get("rule_findings") or []
    if findings:
        st.subheader("Rules")
        for finding in findings:
            url = finding.get("source_url") or ""
            title = finding.get("source_title") or "Source"
            st.markdown(f"- {finding.get('claim')}  \n  Source: [{title}]({url})")
    statuses = _status_for(stay_id)
    packets = plan.get("packets") or []
    if packets:
        st.subheader("Referral drafts")
        st.caption(
            "Edits in the box stay in this browser. Approving records a local status. It does not send the packet."
        )
        for packet in packets:
            ccn = str(packet["facility_ccn"])
            status = statuses.get(ccn, "pending_approval")
            with st.expander(
                f"{packet.get('facility_name')} · {status}", expanded=packet is packets[0]
            ):
                if status == "sent":
                    st.success(
                        "Status: Sent. This is a local record. The packet was not transmitted."
                    )
                elif status == "declined":
                    st.warning("Status: Declined.")
                highlighted = str(packet.get("markdown") or "").replace(
                    "[NEEDS INPUT]",
                    "<mark>[NEEDS INPUT]</mark>",
                )
                st.markdown(highlighted, unsafe_allow_html=True)
                missing = packet.get("missing_items") or []
                if missing:
                    st.markdown("**Missing**")
                    for item in missing:
                        st.markdown(f"- {item}")
                with st.expander("Edit draft locally"):
                    st.text_area(
                        "Local edit",
                        value=packet.get("markdown") or "",
                        key=f"edit-{stay_id}-{ccn}",
                        height=140,
                        label_visibility="collapsed",
                    )
                decided = status in {"sent", "declined"}
                approve, reject = st.columns(2)
                if approve.button(
                    "Approve",
                    key=f"approve-{stay_id}-{ccn}",
                    type="primary",
                    disabled=decided,
                ):
                    _send_decision(plan["run_id"], ccn, "approve", stay_id)
                if reject.button("Reject", key=f"reject-{stay_id}-{ccn}", disabled=decided):
                    _send_decision(plan["run_id"], ccn, "reject", stay_id)
    if plan.get("summary"):
        st.subheader("Summary")
        st.markdown(plan["summary"])
    st.subheader("Timeline")
    try:
        events = api_get("/referrals", stay_id=stay_id)
    except requests.RequestException:
        events = []
    if not events:
        st.caption("No status changes yet.")
        return
    st.dataframe(
        [
            {
                "When": event.get("created_at"),
                "Facility": event.get("facility_name") or event.get("facility_ccn"),
                "Status": event.get("status"),
                "Actor": event.get("actor"),
                "Note": event.get("note"),
            }
            for event in events
        ],
        width="stretch",
        hide_index=True,
    )


def _send_decision(run_id: str, facility_ccn: str, decision: str, stay_id: str) -> None:
    try:
        updated = api_post(
            f"/plans/{run_id}/decisions",
            {"facility_ccn": facility_ccn, "decision": decision, "actor": "case_manager"},
        )
    except requests.RequestException as exc:
        st.error(f"Could not record the decision. ({exc})")
        return
    st.session_state[f"plan:{stay_id}"] = updated
    st.rerun()


def page_about() -> None:
    """Model card and limits. The text comes from the API, not from the warehouse."""
    st.title("About")
    try:
        data = api_get("/about")
    except requests.RequestException as exc:
        st.error(f"API unavailable at {API_BASE}. ({exc})")
        return
    st.markdown(f"**Data mode:** {data.get('data_mode')}")
    st.subheader("Limitations")
    for item in data.get("limitations") or []:
        st.markdown(f"- {item}")
    st.subheader("Model card")
    st.markdown(data.get("model_card") or "")
    st.caption("Demo recording script: docs/demo_script.md. Pilot outline: docs/pilot_proposal.md.")


def main() -> None:
    """Sidebar navigation across leadership, the worklist, a patient, and about."""
    st.set_page_config(page_title="ClearBed", layout="wide")
    _guard()
    st.sidebar.markdown("## ClearBed")
    st.sidebar.caption("Discharge barrier copilot")
    if "nav" not in st.session_state:
        st.session_state["nav"] = "Leadership"
    goto = st.session_state.pop("goto", None)
    if goto:
        st.session_state["nav"] = goto
    page = st.sidebar.radio("Navigate", ["Leadership", "Worklist", "Patient", "About"], key="nav")
    pages = {
        "Leadership": page_leadership,
        "Worklist": page_worklist,
        "Patient": page_patient,
        "About": page_about,
    }
    pages[page]()


if __name__ == "__main__":
    main()
