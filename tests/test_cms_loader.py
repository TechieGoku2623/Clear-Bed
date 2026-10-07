"""Tests for the CMS nursing-home loader and the synthetic capability profile."""

from __future__ import annotations

from pathlib import Path

import duckdb

from clearbed.ingest.cms_snf_loader import load_cms_csv, map_headers, normalize_header


def test_header_mapping_accepts_cms_names() -> None:
    columns = [
        "CMS Certification Number (CCN)",
        "Provider Name",
        "Provider Address",
        "City/Town",
        "State",
        "ZIP Code",
        "Number of Certified Beds",
        "Average Number of Residents per Day",
        "Overall Rating",
        "Health Inspection Rating",
        "Staffing Rating",
        "Provider Type",
        "Ownership Type",
        "Latitude",
        "Longitude",
    ]
    mapping = map_headers(columns)
    assert mapping["ccn"] == "CMS Certification Number (CCN)"
    assert normalize_header("City/Town") == "city town"


def test_fixture_keeps_massachusetts_and_floors_open_beds(tmp_path: Path) -> None:
    warehouse = tmp_path / "warehouse.duckdb"
    fixture = Path(__file__).resolve().parent / "fixtures" / "cms" / "nh_provider_info.csv"
    counts = load_cms_csv(fixture, warehouse, seed=42)
    assert counts["cms_snf_ma"] == 9
    con = duckdb.connect(str(warehouse))
    states = {row[0] for row in con.execute("select distinct state from raw.cms_snf_ma").fetchall()}
    assert states == {"MA"}
    full = con.execute("select est_open_beds from raw.cms_snf_ma where ccn = '225009'").fetchone()
    assert full is not None and full[0] == 0
    medicaid = con.execute(
        "select accepts_medicaid from raw.cms_snf_ma where ccn = '225005'"
    ).fetchone()
    assert medicaid is not None and medicaid[0] is False
    missing_geo = con.execute(
        "select latitude, longitude from raw.cms_snf_ma where ccn = '225008'"
    ).fetchone()
    assert missing_geo is not None
    assert missing_geo[0] is not None and missing_geo[1] is not None
    source = con.execute(
        "select distinct capability_source from raw.snf_capabilities_synthetic"
    ).fetchone()
    assert source is not None and source[0] == "synthetic_seeded_profile"
    con.close()
