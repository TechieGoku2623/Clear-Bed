"""Load a Synthea CSV export into the DuckDB ``raw`` schema.

Every CSV under the configured Synthea directory becomes ``raw.<snake_case_stem>``.
Column names are normalized to snake_case. ``_loaded_at`` and ``_source_file`` are
added. Reloading replaces the table, so the job is safe to rerun.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from clearbed.config import Settings, get_settings
from clearbed.logging import get_logger, log_event

logger = get_logger("ingest.synthea")


def snake_case(name: str) -> str:
    """Convert a header or file stem to a safe snake_case identifier."""
    lowered = name.strip().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", lowered)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        raise ValueError(f"Cannot derive an identifier from {name!r}")
    if cleaned[0].isdigit():
        cleaned = f"c_{cleaned}"
    return cleaned


def _dedupe_columns(columns: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    result: list[str] = []
    for column in columns:
        count = seen.get(column, 0)
        seen[column] = count + 1
        result.append(column if count == 0 else f"{column}_{count + 1}")
    return result


def load_synthea_csv_dir(csv_dir: Path, warehouse_path: Path) -> dict[str, int]:
    """Load every CSV in ``csv_dir`` into ``raw`` and return row counts.

    Files are read as strings so identifiers such as ZIP codes keep leading zeros.
    Empty strings stay empty; staging models decide which of those are null.
    """
    if not csv_dir.is_dir():
        raise FileNotFoundError(f"Synthea CSV directory not found: {csv_dir}")
    files = sorted(path for path in csv_dir.glob("*.csv") if path.is_file())
    if not files:
        raise FileNotFoundError(f"No CSV files in {csv_dir}")

    warehouse_path.parent.mkdir(parents=True, exist_ok=True)
    loaded_at = datetime.now(UTC)
    counts: dict[str, int] = {}
    con = duckdb.connect(str(warehouse_path))
    try:
        con.execute("create schema if not exists raw")
        for path in files:
            table = snake_case(path.stem)
            frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            frame.columns = _dedupe_columns([snake_case(str(column)) for column in frame.columns])
            frame["_loaded_at"] = loaded_at
            frame["_source_file"] = path.name
            con.register("_synthea_batch", frame)
            con.execute(f"create or replace table raw.{table} as select * from _synthea_batch")
            con.unregister("_synthea_batch")
            counts[table] = int(len(frame))
            log_event(
                logger,
                "loaded synthea table",
                table=table,
                rows=counts[table],
                source_file=path.name,
            )
    finally:
        con.close()
    return counts


def format_summary(counts: dict[str, int]) -> str:
    """Return a fixed-width row-count table for the load summary."""
    if not counts:
        return "No tables loaded."
    width = max(len(name) for name in counts)
    lines = [f"{'table':<{width + 4}}  rows", f"{'-' * (width + 4)}  ----"]
    for name in sorted(counts):
        lines.append(f"raw.{name:<{width}}  {counts[name]}")
    return "\n".join(lines)


def main() -> None:
    """Load the configured Synthea export and print row counts."""
    settings: Settings = get_settings()
    counts = load_synthea_csv_dir(settings.synthea_csv_dir, settings.resolved_warehouse_path)
    print(format_summary(counts))


if __name__ == "__main__":
    main()
