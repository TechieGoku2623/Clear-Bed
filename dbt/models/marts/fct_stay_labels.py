"""Synthetic discharge-barrier labels.

Synthea does not record discharge disposition or the reason a patient stayed
past medical readiness. This model applies the seeded rules in
``seeds/labeling_rules.csv`` through ``clearbed.features.labeling``.

With PhysioNet credentialing, replace this model with labels built from
MIMIC-IV ``admissions.discharge_location`` and length of stay.
"""

from __future__ import annotations

def model(dbt, session):  # noqa: ANN001
    """Return one label row per inpatient stay."""
    dbt.config(materialized="table")
    from clearbed.features.labeling import assign_labels

    stays = dbt.ref("fct_inpatient_stays")
    rules = dbt.ref("labeling_rules")
    try:
        stay_df = stays.df()
        rule_df = rules.df()
    except AttributeError:
        stay_df = session.sql(f"select * from {stays}").df()
        rule_df = session.sql(f"select * from {rules}").df()
    return assign_labels(stay_df, rule_df)
