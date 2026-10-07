"""Load the committed tiny fixtures into a DuckDB file for dbt CI.

The fixture is synthetic and small. It exercises the same loaders as the full
pipeline so ``dbt build`` can run without Synthea or a CMS download.
"""

from __future__ import annotations

from pathlib import Path

from clearbed.config import repo_root
from clearbed.ingest.cms_snf_loader import load_cms_csv
from clearbed.ingest.synthea_loader import load_synthea_csv_dir


def fixture_root() -> Path:
    """Return the committed fixture directory."""
    return repo_root() / "tests" / "fixtures"


def load_fixtures(warehouse_path: Path) -> dict[str, int]:
    """Load Synthea and CMS fixtures into ``warehouse_path``."""
    synthea_counts = load_synthea_csv_dir(fixture_root() / "synthea", warehouse_path)
    cms_counts = load_cms_csv(
        fixture_root() / "cms" / "nh_provider_info.csv", warehouse_path, seed=42
    )
    return {**synthea_counts, **cms_counts}


def main() -> None:
    """Write the fixture warehouse configured by ``WAREHOUSE_PATH``."""
    from clearbed.config import get_settings

    settings = get_settings()
    counts = load_fixtures(settings.resolved_warehouse_path)
    for name in sorted(counts):
        print(f"{name}  {counts[name]}")


if __name__ == "__main__":
    main()
