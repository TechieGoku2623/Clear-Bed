-- Features known at admission. Length of stay, discharge time, and labels
-- are intentionally absent so a model cannot train on the outcome.
with stays as (
    select * from {{ ref('fct_inpatient_stays') }}
),
expected as (
    select * from {{ ref('int_expected_los') }}
),
global_los as (
    select median(los_days) as global_expected_los
    from stays
)
select
    s.stay_id,
    s.patient_id,
    s.admit_ts,
    s.admit_dow,
    s.admit_month,
    s.age_at_admit,
    s.age_band,
    s.gender,
    s.race,
    s.ethnicity,
    s.zip,
    s.county,
    s.condition_group,
    s.payer_type,
    s.prior_admits_12m,
    s.prior_ed_visits_12m,
    s.n_active_meds,
    s.flag_dementia,
    s.flag_ckd_dialysis,
    s.flag_copd,
    s.flag_chf,
    s.flag_obesity,
    s.flag_behavioral,
    s.flag_substance,
    s.flag_home_o2,
    s.lives_alone_proxy,
    coalesce(e.expected_los_days, g.global_expected_los) as expected_los_days
from stays as s
left join expected as e
    on s.condition_group = e.condition_group
    and s.age_band = e.age_band
cross join global_los as g
