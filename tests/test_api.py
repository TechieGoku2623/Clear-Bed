"""API happy path against the mini warehouse."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clearbed.agent.graph import clear_graph_cache
from clearbed.api.main import app
from clearbed.config import get_settings
from clearbed.eval.mini_warehouse import build_mini_warehouse


def _client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    warehouse = tmp_path / "warehouse.duckdb"
    build_mini_warehouse(warehouse)
    monkeypatch.setenv("WAREHOUSE_PATH", str(warehouse))
    monkeypatch.setenv("CHECKPOINT_PATH", str(tmp_path / "checkpoints.sqlite"))
    monkeypatch.setenv("DATA_MODE", "synthetic")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("API_KEY", "test-key")
    get_settings.cache_clear()
    clear_graph_cache()
    return TestClient(app)


def test_health_and_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/worklist").status_code == 401


def test_plan_approve_and_leadership(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = _client(tmp_path, monkeypatch)
    headers = {"X-API-Key": "test-key"}
    worklist = client.get("/worklist", headers=headers)
    assert worklist.status_code == 200
    assert len(worklist.json()) == 5
    high = client.get("/worklist", headers=headers, params={"tier": "high"})
    assert high.status_code == 200
    assert all(row["risk_tier"] == "high" for row in high.json())
    patient = client.get("/patients/stay-post", headers=headers)
    assert patient.status_code == 200
    assert patient.json()["workflow_route"] == "post_acute_placement"
    created = client.post("/plans", headers=headers, json={"stay_id": "stay-post"})
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "awaiting_approval"
    ccn = body["packets"][0]["facility_ccn"]
    decided = client.post(
        f"/plans/{body['run_id']}/decisions",
        headers=headers,
        json={"facility_ccn": ccn, "decision": "approve"},
    )
    assert decided.status_code == 200
    assert decided.json()["status"] == "complete"
    referrals = client.get("/referrals", headers=headers, params={"stay_id": "stay-post"})
    assert referrals.status_code == 200
    assert referrals.json()[0]["status"] == "sent"
    board = client.get("/leadership", headers=headers)
    assert board.status_code == 200
    payload = board.json()
    assert payload["banner"] == "Synthetic data — demo only"
    assert "assumed" in payload["cost_note"].lower() or "$" in payload["cost_note"]
    assert payload["referrals_by_status"].get("sent") == 1
    assert payload["simulated_backcast"] is True
    about = client.get("/about", headers=headers)
    assert about.status_code == 200
    assert "model_card" in about.json()
