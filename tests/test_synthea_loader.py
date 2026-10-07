"""Tests for the Synthea CSV loader."""

from __future__ import annotations

from pathlib import Path

import duckdb

from clearbed.ingest.synthea_loader import format_summary, load_synthea_csv_dir, snake_case


def test_snake_case() -> None:
    assert snake_case("TOTAL_CLAIM_COST") == "total_claim_cost"
    assert snake_case("City/Town") == "city_town"


def test_loader_is_idempotent(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    fixture = Path(__file__).resolve().parent / "fixtures" / "synthea"
    first = load_synthea_csv_dir(fixture, warehouse)
    second = load_synthea_csv_dir(fixture, warehouse)
    assert first["patients"] == 6
    assert second["patients"] == 6
    assert "encounters" in first
    con = duckdb.connect(str(warehouse))
    columns = [row[0] for row in con.execute("describe raw.patients").fetchall()]
    assert "birthdate" in columns
    assert "_loaded_at" in columns
    assert "_source_file" in columns
    count = con.execute("select count(*) from raw.patients").fetchone()
    assert count is not None and count[0] == 6
    con.close()
    summary = format_summary(first)
    assert "raw.patients" in summary
