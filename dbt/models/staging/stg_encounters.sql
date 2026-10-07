select
    id as encounter_id,
    patient as patient_id,
    try_cast(nullif(start, '') as timestamp) as start_ts,
    try_cast(nullif(stop, '') as timestamp) as stop_ts,
    lower(encounterclass) as encounter_class,
    code,
    description,
    organization as organization_id,
    payer as payer_id,
    try_cast(nullif(total_claim_cost, '') as double) as total_cost,
    nullif(reasoncode, '') as reason_code,
    nullif(reasondescription, '') as reason_description
from {{ source('raw', 'encounters') }}
