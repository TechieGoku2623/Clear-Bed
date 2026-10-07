"""A tiny DuckDB warehouse for tests and the agent eval.

The rows are invented. They let CI exercise routing, hard filters, and the
approval interrupt without Synthea or the CMS download.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from clearbed.warehouse import ensure_app_schema


def build_mini_warehouse(path: Path) -> None:
    """Create ``path`` with five stays and four Massachusetts-shaped facilities."""
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect_path(path)
    try:
        ensure_app_schema(con)
        con.execute("create schema if not exists staging")
        con.execute("create schema if not exists marts")
        con.execute(
            """
            create table staging.stg_snf (
                ccn varchar, facility_name varchar, city varchar, zip varchar,
                latitude double, longitude double, overall_rating double,
                est_open_beds integer, typical_response_hours double,
                accepts_medicaid boolean, provider_type varchar,
                accepts_dialysis boolean, accepts_trach_vent boolean,
                accepts_behavioral boolean, accepts_bariatric boolean
            )
            """
        )
        con.execute(
            """
            create table staging.stg_conditions (
                patient_id varchar, description varchar, start_ts timestamp, stop_ts timestamp
            )
            """
        )
        con.execute(
            """
            create table staging.stg_medications (
                patient_id varchar, description varchar, start_ts timestamp, stop_ts timestamp
            )
            """
        )
        con.execute(
            """
            create table staging.stg_procedures (
                patient_id varchar, description varchar, start_ts timestamp
            )
            """
        )
        con.execute(
            """
            create table marts.feat_admission_snapshot (
                stay_id varchar, patient_id varchar, age_at_admit integer, admit_ts timestamp,
                flag_dementia integer, flag_chf integer, flag_copd integer, flag_home_o2 integer,
                flag_obesity integer, flag_behavioral integer, flag_ckd_dialysis integer,
                lives_alone_proxy integer
            )
            """
        )
        con.executemany(
            """
            insert into staging.stg_snf values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "225001",
                    "FIXTURE Boston SNF",
                    "Boston",
                    "02118",
                    42.35,
                    -71.06,
                    4.0,
                    12,
                    24.0,
                    True,
                    "Medicare and Medicaid",
                    True,
                    True,
                    True,
                    True,
                ),
                (
                    "225002",
                    "FIXTURE Full House",
                    "Boston",
                    "02115",
                    42.34,
                    -71.07,
                    3.0,
                    0,
                    48.0,
                    True,
                    "Medicare and Medicaid",
                    True,
                    True,
                    True,
                    True,
                ),
                (
                    "225003",
                    "FIXTURE Medicaid Only",
                    "Roxbury",
                    "02119",
                    42.33,
                    -71.09,
                    3.0,
                    8,
                    24.0,
                    True,
                    "Medicaid",
                    False,
                    False,
                    False,
                    False,
                ),
                (
                    "225004",
                    "FIXTURE Far Away",
                    "New York",
                    "10001",
                    40.75,
                    -73.99,
                    5.0,
                    20,
                    12.0,
                    True,
                    "Medicare and Medicaid",
                    True,
                    True,
                    True,
                    True,
                ),
            ],
        )
        stays = [
            (
                "stay-post",
                "p-post",
                "75-84",
                "hip_fracture",
                "medicare",
                4,
                6.0,
                0.82,
                "high",
                "post_acute_placement",
                82,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ),
            (
                "stay-payer",
                "p-payer",
                "65-74",
                "heart_failure",
                "none",
                2,
                5.0,
                0.55,
                "medium",
                "payer_pending",
                70,
                0,
                1,
                0,
                0,
                0,
                0,
                0,
            ),
            (
                "stay-guard",
                "p-guard",
                "85+",
                "dementia",
                "medicare",
                3,
                7.0,
                0.7,
                "high",
                "none",
                86,
                1,
                0,
                0,
                0,
                0,
                0,
                1,
            ),
            (
                "stay-home",
                "p-home",
                "65-74",
                "heart_failure",
                "medicare",
                2,
                4.0,
                0.4,
                "medium",
                "none",
                72,
                0,
                1,
                0,
                1,
                0,
                0,
                0,
            ),
            (
                "stay-none",
                "p-none",
                "18-44",
                "appendicitis",
                "commercial",
                1,
                2.0,
                0.1,
                "low",
                "none",
                34,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
            ),
        ]
        for stay in stays:
            (
                stay_id,
                patient_id,
                age_band,
                group,
                payer,
                day,
                expected,
                prob,
                tier,
                barrier,
                age,
                dementia,
                chf,
                copd,
                home_o2,
                obesity,
                behavioral,
                alone,
            ) = stay
            con.execute(
                """
                insert into app.worklist (
                    stay_id, patient_id, age_band, condition_group, payer_type, day_of_stay,
                    expected_los, stuck_prob, risk_tier, predicted_barrier, barrier_prob,
                    predicted_avoidable_days, top_reasons, scored_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, current_timestamp)
                """,
                [
                    stay_id,
                    patient_id,
                    age_band,
                    group,
                    payer,
                    day,
                    expected,
                    prob,
                    tier,
                    barrier,
                    prob,
                    3.0,
                    '[{"label": "Age at admission", "direction": "increases risk"}, '
                    '{"label": "Condition group", "direction": "increases risk"}, '
                    '{"label": "Payer at admission", "direction": "increases risk"}, '
                    '{"label": "Lives alone (synthetic proxy)", "direction": "increases risk"}, '
                    '{"label": "Expected length of stay", "direction": "increases risk"}]',
                ],
            )
            con.execute(
                """
                insert into marts.feat_admission_snapshot values (
                    ?, ?, ?, timestamp '2024-06-01', ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                [
                    stay_id,
                    patient_id,
                    age,
                    dementia,
                    chf,
                    copd,
                    home_o2,
                    obesity,
                    behavioral,
                    0,
                    alone,
                ],
            )
        con.execute(
            "insert into staging.stg_conditions values (?, ?, timestamp '2024-05-01', null)",
            ["p-post", "Closed fracture of neck of femur"],
        )
        con.execute(
            "insert into staging.stg_medications values (?, ?, timestamp '2024-05-01', null)",
            ["p-post", "acetaminophen"],
        )
        con.execute(
            "insert into staging.stg_procedures values (?, ?, timestamp '2024-06-01')",
            ["p-post", "Hemodialysis"],
        )
        con.execute(
            """
            insert into app.daily_summary (
                total_census, high_risk_count, projected_avoidable_bed_days,
                estimated_cost, cost_per_bed_day, scored_at
            ) values (5, 2, 8.5, 21250, 2500, current_timestamp)
            """
        )
    finally:
        con.close()


def connect_path(path: Path) -> duckdb.DuckDBPyConnection:
    """Open a duckdb file, creating parent folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))
