"""DuckDB connection helpers and the application schema.

The warehouse holds Synthea raw tables, dbt marts, and the small ``app`` schema
the API writes to. Connections are opened per call so CLI jobs and the API do
not share a long-lived handle.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb

from clearbed.config import Settings, get_settings

APP_SCHEMA_SQL = """
create schema if not exists app;

create table if not exists app.worklist (
    stay_id varchar,
    patient_id varchar,
    age_band varchar,
    condition_group varchar,
    payer_type varchar,
    day_of_stay integer,
    expected_los double,
    stuck_prob double,
    risk_tier varchar,
    predicted_barrier varchar,
    barrier_prob double,
    predicted_avoidable_days double,
    top_reasons varchar,
    scored_at timestamp
);

create table if not exists app.daily_summary (
    total_census integer,
    high_risk_count integer,
    projected_avoidable_bed_days double,
    estimated_cost double,
    cost_per_bed_day double,
    scored_at timestamp
);

create table if not exists app.referrals (
    referral_id varchar,
    stay_id varchar,
    facility_ccn varchar,
    facility_name varchar,
    status varchar,
    note varchar,
    actor varchar,
    run_id varchar,
    created_at timestamp,
    updated_at timestamp
);

create table if not exists app.referral_events (
    event_id varchar,
    referral_id varchar,
    stay_id varchar,
    facility_ccn varchar,
    status varchar,
    note varchar,
    actor varchar,
    created_at timestamp
);

create table if not exists app.audit_log (
    audit_id varchar,
    actor varchar,
    action varchar,
    entity varchar,
    entity_id varchar,
    detail varchar,
    created_at timestamp
);

create table if not exists app.agent_runs (
    run_id varchar,
    stay_id varchar,
    status varchar,
    state_json varchar,
    created_at timestamp,
    updated_at timestamp
);
"""


def connect(
    settings: Settings | None = None, *, read_only: bool = False
) -> duckdb.DuckDBPyConnection:
    """Open the configured DuckDB warehouse, creating parent directories."""
    settings = settings or get_settings()
    path: Path = settings.resolved_warehouse_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path), read_only=read_only)


def ensure_app_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the ``app`` tables used by scoring, referrals, and the API."""
    con.execute(APP_SCHEMA_SQL)


def audit(
    con: duckdb.DuckDBPyConnection,
    *,
    actor: str,
    action: str,
    entity: str,
    entity_id: str,
    detail: str,
) -> None:
    """Append an audit row. ``detail`` must not contain a patient record."""
    ensure_app_schema(con)
    con.execute(
        """
        insert into app.audit_log (audit_id, actor, action, entity, entity_id, detail, created_at)
        values (?, ?, ?, ?, ?, ?, current_timestamp)
        """,
        [str(uuid.uuid4()), actor, action, entity, entity_id, detail],
    )
