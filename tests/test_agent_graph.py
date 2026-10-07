"""Approval interrupt: one human approval records status sent exactly once."""

from __future__ import annotations

import duckdb

from clearbed.agent.graph import clear_graph_cache, decide, start_run
from clearbed.config import Settings
from clearbed.eval.mini_warehouse import build_mini_warehouse


def _settings(tmp_path) -> Settings:  # type: ignore[no-untyped-def]
    warehouse = tmp_path / "warehouse.duckdb"
    build_mini_warehouse(warehouse)
    clear_graph_cache()
    return Settings(
        data_mode="synthetic",
        llm_provider="mock",
        environment="dev",
        warehouse_path=warehouse,
        checkpoint_path=tmp_path / "checkpoints.sqlite",
        api_key="test-key",
    )


def test_post_acute_approval_is_sent_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    view = start_run("stay-post", settings)
    assert view["status"] == "awaiting_approval"
    assert view["packets"]
    assert view["facilities"]
    assert all(item["ccn"] == "225001" for item in view["facilities"])
    assert any("source_url" in item and item["source_url"] for item in view["rule_findings"])
    ccn = view["packets"][0]["facility_ccn"]
    updated = decide(view["run_id"], facility_ccn=ccn, decision="approve", settings=settings)
    assert updated["status"] == "complete"
    assert "Citations:" in updated["summary"]
    con = duckdb.connect(str(settings.resolved_warehouse_path), read_only=True)
    try:
        status = con.execute(
            "select status from app.referrals where stay_id = ? and facility_ccn = ?",
            ["stay-post", ccn],
        ).fetchone()
        events = con.execute(
            "select count(*) from app.referral_events where stay_id = ? and facility_ccn = ?",
            ["stay-post", ccn],
        ).fetchone()
    finally:
        con.close()
    assert status is not None
    assert status[0] == "sent"
    assert events is not None
    assert events[0] == 1


def test_payer_route_has_no_facility_packet(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    view = start_run("stay-payer", settings)
    assert view["barrier"] == "payer_pending"
    assert view["facilities"] == []
    assert view["pending_approvals"][0]["facility_ccn"] == "ACTION"
    assert view["status"] == "awaiting_approval"


def test_guardianship_does_not_draft(tmp_path) -> None:  # type: ignore[no-untyped-def]
    settings = _settings(tmp_path)
    view = start_run("stay-guard", settings)
    assert view["barrier"] == "guardianship_capacity"
    assert view["packets"] == []
    assert view["status"] == "complete"
