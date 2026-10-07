-- Patient identifiers that are not needed for modeling are dropped here.
-- Name, SSN, address, and document numbers never leave the raw schema.
select
    id as patient_id,
    try_cast(nullif(birthdate, '') as date) as birthdate,
    try_cast(nullif(deathdate, '') as date) as deathdate,
    gender,
    race,
    ethnicity,
    zip,
    county,
    date_diff('year', try_cast(nullif(birthdate, '') as date), current_date) as age_today
from {{ source('raw', 'patients') }}
