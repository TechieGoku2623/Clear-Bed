"""Load CMS Care Compare nursing homes and a synthetic acceptance profile.

Real columns come from the CMS "Nursing Home Provider Information" file.
Headers are inspected and mapped; they are not assumed to arrive under one
spelling. Only Massachusetts rows are kept. Missing coordinates are filled
from ZIP centroids.

``raw.snf_capabilities_synthetic`` is seeded and synthetic. CMS does not
publish dialysis, trach/vent, behavioral, bariatric, or response-time flags.
That table is labeled ``capability_source = synthetic_seeded_profile``.
"""

from __future__ import annotations

import random
import re
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from clearbed.config import Settings, get_settings
from clearbed.logging import get_logger, log_event

logger = get_logger("ingest.cms")

# Normalized header text -> canonical column. Matching is by inspected header,
# so a renamed CMS export still loads when one of these aliases is present.
HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "ccn": (
        "cms certification number (ccn)",
        "cms certification number",
        "federal provider number",
        "provnum",
        "ccn",
    ),
    "facility_name": ("provider name", "facility name", "provname"),
    "address": ("provider address", "address"),
    "city": ("city/town", "city town", "city"),
    "state": ("state",),
    "zip": ("zip code", "zip"),
    "certified_beds": ("number of certified beds", "certified beds", "bedcert"),
    "avg_residents_per_day": (
        "average number of residents per day",
        "avg residents per day",
        "restot",
    ),
    "overall_rating": ("overall rating",),
    "health_inspection_rating": ("health inspection rating",),
    "staffing_rating": ("staffing rating",),
    "provider_type": ("provider type",),
    "ownership_type": ("ownership type",),
    "latitude": ("latitude", "lat"),
    "longitude": ("longitude", "lon", "long"),
}

CANONICAL_COLUMNS = list(HEADER_ALIASES)


def normalize_header(header: str) -> str:
    """Lowercase a header and collapse punctuation so aliases can match."""
    text = header.strip().lower()
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def map_headers(columns: list[str]) -> dict[str, str]:
    """Map original column names onto the canonical SNF schema.

    Raises ``KeyError`` listing any canonical field that no header matched.
    """
    normalized = {normalize_header(column): column for column in columns}
    alias_index = {
        normalize_header(alias): canonical
        for canonical, aliases in HEADER_ALIASES.items()
        for alias in aliases
    }
    mapping: dict[str, str] = {}
    for header, original in normalized.items():
        canonical = alias_index.get(header)
        if canonical and canonical not in mapping:
            mapping[canonical] = original
    missing = [canonical for canonical in HEADER_ALIASES if canonical not in mapping]
    if missing:
        raise KeyError(
            "CMS file is missing expected columns: "
            + ", ".join(missing)
            + ". Inspected headers: "
            + ", ".join(columns[:40])
        )
    return mapping


def _zip5(value: Any) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    return digits.zfill(5)[:5]


def _to_float(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def geocode_missing(frame: pd.DataFrame) -> pd.DataFrame:
    """Fill blank latitude/longitude from the US ZIP centroid file."""
    missing = frame["latitude"].isna() | frame["longitude"].isna()
    if not bool(missing.any()):
        return frame
    import pgeocode

    nomi = pgeocode.Nominatim("us")
    zips = frame.loc[missing, "zip"].tolist()
    looked = nomi.query_postal_code(zips)
    if isinstance(looked, pd.Series):
        looked = looked.to_frame().T
    frame.loc[missing, "latitude"] = looked["latitude"].to_numpy()
    frame.loc[missing, "longitude"] = looked["longitude"].to_numpy()
    return frame


def clean_cms_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Map headers, keep Massachusetts, and derive open-bed and Medicaid flags."""
    mapping = map_headers([str(column) for column in raw.columns])
    frame = pd.DataFrame({canonical: raw[original] for canonical, original in mapping.items()})
    frame["state"] = frame["state"].astype(str).str.strip().str.upper()
    frame = frame.loc[frame["state"].isin(["MA", "MASSACHUSETTS"])].copy()
    frame["state"] = "MA"
    frame["zip"] = frame["zip"].map(_zip5)
    frame["ccn"] = frame["ccn"].astype(str).str.strip()
    frame = frame.loc[frame["ccn"].ne("") & frame["ccn"].ne("nan")]
    for column in (
        "certified_beds",
        "avg_residents_per_day",
        "overall_rating",
        "health_inspection_rating",
        "staffing_rating",
        "latitude",
        "longitude",
    ):
        frame[column] = _to_float(frame[column])
    frame = geocode_missing(frame)
    beds = frame["certified_beds"].fillna(0)
    residents = frame["avg_residents_per_day"].fillna(0)
    frame["est_open_beds"] = np.floor(beds - residents).clip(lower=0).astype(int)
    provider = frame["provider_type"].astype(str)
    frame["accepts_medicaid"] = provider.str.contains("medicaid", case=False, na=False)
    frame["facility_name"] = frame["facility_name"].astype(str).str.strip()
    frame["address"] = frame["address"].astype(str).str.strip()
    frame["city"] = frame["city"].astype(str).str.strip()
    frame["provider_type"] = provider.str.strip()
    frame["ownership_type"] = frame["ownership_type"].astype(str).str.strip()
    return frame.reset_index(drop=True)


def synthetic_capabilities(ccns: list[str], seed: int) -> pd.DataFrame:
    """Build a seeded, clearly synthetic acceptance profile per facility.

    The draw is a function of ``seed`` and CCN, so the same file reloads to
    the same profile. This is not a CMS measure.
    """
    rows: list[dict[str, Any]] = []
    for ccn in ccns:
        rng = random.Random(f"{seed}:{ccn}")
        rows.append(
            {
                "ccn": ccn,
                "accepts_dialysis": rng.random() < 0.35,
                "accepts_trach_vent": rng.random() < 0.15,
                "accepts_behavioral": rng.random() < 0.40,
                "accepts_bariatric": rng.random() < 0.30,
                "typical_response_hours": rng.choice([4, 8, 12, 24, 48, 72]),
                "capability_source": "synthetic_seeded_profile",
            }
        )
    return pd.DataFrame(rows)


def ensure_cms_csv(settings: Settings, *, refresh: bool = False) -> Path:
    """Return the local CMS CSV, downloading it when the file is absent."""
    path = settings.resolved_cms_csv
    if path.exists() and path.stat().st_size > 0 and not refresh:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    log_event(logger, "downloading cms nursing home file", url=settings.cms_snf_url)
    urllib.request.urlretrieve(settings.cms_snf_url, path)  # noqa: S310
    return path


def load_cms_csv(csv_path: Path, warehouse_path: Path, *, seed: int = 42) -> dict[str, int]:
    """Load Massachusetts SNFs and the synthetic capability table."""
    raw = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    clean = clean_cms_frame(raw)
    capabilities = synthetic_capabilities(clean["ccn"].tolist(), seed)
    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    import duckdb

    con = duckdb.connect(str(warehouse_path))
    try:
        con.execute("create schema if not exists raw")
        con.register("_cms", clean)
        con.execute("create or replace table raw.cms_snf_ma as select * from _cms")
        con.register("_cap", capabilities)
        con.execute("create or replace table raw.snf_capabilities_synthetic as select * from _cap")
        con.unregister("_cms")
        con.unregister("_cap")
    finally:
        con.close()
    log_event(
        logger,
        "loaded cms snf tables",
        facilities=int(len(clean)),
        capabilities=int(len(capabilities)),
        capability_source="synthetic_seeded_profile",
    )
    return {"cms_snf_ma": int(len(clean)), "snf_capabilities_synthetic": int(len(capabilities))}


def main() -> None:
    """Download the CMS file if needed, load MA facilities, and print counts."""
    settings = get_settings()
    path = ensure_cms_csv(settings)
    counts = load_cms_csv(path, settings.resolved_warehouse_path, seed=settings.synthea_seed)
    print(f"raw.cms_snf_ma  {counts['cms_snf_ma']}")
    print(
        "raw.snf_capabilities_synthetic  "
        f"{counts['snf_capabilities_synthetic']}  (synthetic seeded profile, not CMS)"
    )


if __name__ == "__main__":
    main()
