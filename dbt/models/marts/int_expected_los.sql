-- Median length of stay for a condition group and age band.
-- This is a historical baseline. It is not the patient's own length of stay.
select
    condition_group,
    age_band,
    median(los_days) as expected_los_days,
    count(*) as n_stays
from {{ ref('fct_inpatient_stays') }}
group by condition_group, age_band
