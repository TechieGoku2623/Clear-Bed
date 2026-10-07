"""Data-quality report for the ClearBed marts.

The HTML report is for a human review. The process exits non-zero when a
critical check fails: model-feature nulls above 5%, leakage columns on the
admission snapshot, or fewer than 500 inpatient stays.
"""

from __future__ import annotations

import html
from pathlib import Path

import duckdb
import pandas as pd

from clearbed.config import Settings, get_settings
from clearbed.ml.feature_labels import LEAKAGE_COLUMNS, model_feature_columns
from clearbed.warehouse import connect

MIN_STAYS = 500
MAX_NULL_RATE = 0.05


def _table_exists(con: duckdb.DuckDBPyConnection, schema: str, table: str) -> bool:
    row = con.execute(
        """
        select count(*)
        from information_schema.tables
        where table_schema = ? and table_name = ?
        """,
        [schema, table],
    ).fetchone()
    return bool(row and row[0])


def load_frames(con: duckdb.DuckDBPyConnection) -> dict[str, pd.DataFrame]:
    """Read the marts the report summarizes."""
    required = {
        "stays": "select * from marts.fct_inpatient_stays",
        "labels": "select * from marts.fct_stay_labels",
        "features": "select * from marts.feat_admission_snapshot",
    }
    frames: dict[str, pd.DataFrame] = {}
    for name, query in required.items():
        frames[name] = con.execute(query).df()
    return frames


def null_rates(features: pd.DataFrame) -> pd.DataFrame:
    """Null rate for each model feature column."""
    rows = []
    n = max(len(features), 1)
    for column in model_feature_columns():
        if column not in features.columns:
            rows.append({"column": column, "null_rate": 1.0, "missing_column": True})
            continue
        rate = float(features[column].isna().mean()) if n else 0.0
        rows.append({"column": column, "null_rate": rate, "missing_column": False})
    return pd.DataFrame(rows)


def leakage_columns(con: duckdb.DuckDBPyConnection) -> list[str]:
    """Return outcome columns that leaked onto the admission snapshot."""
    rows = con.execute(
        """
        select lower(column_name) as column_name
        from information_schema.columns
        where table_schema = 'marts' and table_name = 'feat_admission_snapshot'
        """
    ).fetchall()
    present = {row[0] for row in rows}
    return sorted(present & set(LEAKAGE_COLUMNS))


def evaluate_checks(
    *,
    n_stays: int,
    nulls: pd.DataFrame,
    leaked: list[str],
    min_stays: int = MIN_STAYS,
    max_null_rate: float = MAX_NULL_RATE,
) -> list[str]:
    """Return human-readable critical failures. An empty list means pass."""
    failures: list[str] = []
    if n_stays < min_stays:
        failures.append(f"Fewer than {min_stays} inpatient stays (found {n_stays}).")
    if leaked:
        failures.append("Label leakage columns present: " + ", ".join(leaked) + ".")
    hot = nulls.loc[nulls["null_rate"] > max_null_rate]
    if not hot.empty:
        detail = ", ".join(f"{row.column}={row.null_rate:.1%}" for row in hot.itertuples())
        failures.append(f"Model features exceed {max_null_rate:.0%} nulls: {detail}.")
    return failures


def _bar_rows(frame: pd.DataFrame, label_col: str, value_col: str) -> str:
    if frame.empty:
        return "<p>No rows.</p>"
    peak = float(frame[value_col].max()) or 1.0
    items: list[str] = []
    for row in frame.itertuples(index=False):
        label = html.escape(str(getattr(row, label_col)))
        value = float(getattr(row, value_col))
        width = max(2, int(100 * value / peak))
        items.append(
            "<div class='row'>"
            f"<span class='label'>{label}</span>"
            f"<span class='bar' style='width:{width}%'></span>"
            f"<span class='value'>{value:.2f}</span>"
            "</div>"
        )
    return "\n".join(items)


def render_html(
    *,
    n_stays: int,
    nulls: pd.DataFrame,
    leaked: list[str],
    failures: list[str],
    labels: pd.DataFrame,
    stays: pd.DataFrame,
) -> str:
    """Render the quality report as a single HTML document."""
    balance = (
        labels.groupby("barrier_type")
        .agg(n=("stay_id", "count"), avg_avoidable_days=("avoidable_days", "mean"))
        .reset_index()
        .sort_values("n", ascending=False)
    )
    conditions = (
        stays.groupby("condition_group")
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
        .head(15)
    )
    payers = (
        stays.groupby("payer_type").size().reset_index(name="n").sort_values("n", ascending=False)
    )
    status = "PASS" if not failures else "FAIL"
    failure_html = (
        "<ul>" + "".join(f"<li>{html.escape(item)}</li>" for item in failures) + "</ul>"
        if failures
        else "<p>No critical checks failed.</p>"
    )
    null_rows = "".join(
        f"<tr><td>{html.escape(str(row.column))}</td><td>{row.null_rate:.1%}</td></tr>"
        for row in nulls.itertuples()
    )
    balance_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(row.barrier_type))}</td>"
        f"<td>{int(row.n)}</td>"
        f"<td>{row.avg_avoidable_days:.2f}</td>"
        "</tr>"
        for row in balance.itertuples()
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>ClearBed data quality</title>
<style>
body {{ font-family: "Segoe UI", Helvetica, sans-serif; margin: 32px; color: #16343d; background: #f4f7f7; }}
h1 {{ margin-bottom: 0; }}
.banner {{ background: #f8f1de; border: 1px solid #e0d2a8; padding: 10px 14px; margin: 16px 0; }}
table {{ border-collapse: collapse; background: white; margin-bottom: 24px; }}
th, td {{ border: 1px solid #d5e0e2; padding: 6px 10px; text-align: left; }}
th {{ background: #e7eef0; }}
.row {{ display: flex; align-items: center; gap: 8px; margin: 4px 0; }}
.label {{ width: 220px; }}
.bar {{ display: inline-block; height: 12px; background: #1f6f78; }}
.value {{ color: #35555c; }}
.fail {{ color: #8d2f39; }}
.pass {{ color: #1e6b45; }}
</style>
</head>
<body>
<h1>ClearBed data quality</h1>
<p class="banner">Synthetic Synthea patients. SNF capability flags are synthetic. This is a demo report.</p>
<p>Status: <strong class="{status.lower()}">{status}</strong> · Inpatient stays: {n_stays}</p>
<h2>Critical checks</h2>
{failure_html}
<p>Leakage columns found: {html.escape(", ".join(leaked) if leaked else "none")}.</p>
<h2>Label balance</h2>
<table><tr><th>Barrier</th><th>Stays</th><th>Avg avoidable days</th></tr>{balance_rows}</table>
<h2>Average avoidable days by barrier</h2>
{_bar_rows(balance, "barrier_type", "avg_avoidable_days")}
<h2>Top condition groups</h2>
{_bar_rows(conditions, "condition_group", "n")}
<h2>Payer mix</h2>
{_bar_rows(payers, "payer_type", "n")}
<h2>Null rates on model features</h2>
<table><tr><th>Column</th><th>Null rate</th></tr>{null_rows}</table>
</body>
</html>
"""


def build_report(
    settings: Settings | None = None, *, min_stays: int = MIN_STAYS
) -> tuple[Path, list[str]]:
    """Write the HTML report and return its path plus any critical failures."""
    settings = settings or get_settings()
    con = connect(settings)
    try:
        if not _table_exists(con, "marts", "fct_inpatient_stays"):
            raise RuntimeError("Marts are missing. Run make dbt before make data-quality.")
        frames = load_frames(con)
        leaked = leakage_columns(con)
    finally:
        con.close()
    nulls = null_rates(frames["features"])
    failures = evaluate_checks(
        n_stays=len(frames["stays"]),
        nulls=nulls,
        leaked=leaked,
        min_stays=min_stays,
    )
    settings.resolved_reports_dir.mkdir(parents=True, exist_ok=True)
    path = settings.resolved_reports_dir / "data_quality.html"
    path.write_text(
        render_html(
            n_stays=len(frames["stays"]),
            nulls=nulls,
            leaked=leaked,
            failures=failures,
            labels=frames["labels"],
            stays=frames["stays"],
        ),
        encoding="utf-8",
    )
    return path, failures


def main() -> None:
    """Write the report and exit non-zero when a critical check fails."""
    path, failures = build_report()
    print(f"Wrote {path}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        raise SystemExit(1)
    print("Critical checks passed.")


if __name__ == "__main__":
    main()
