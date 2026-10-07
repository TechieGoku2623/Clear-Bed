select
    patient as patient_id,
    encounter as encounter_id,
    payer as payer_id,
    try_cast(nullif(start, '') as timestamp) as start_ts,
    try_cast(nullif(stop, '') as timestamp) as stop_ts,
    code,
    description,
    try_cast(nullif(dispenses, '') as integer) as dispenses,
    try_cast(nullif(totalcost, '') as double) as total_cost,
    nullif(reasoncode, '') as reason_code,
    nullif(reasondescription, '') as reason_description
from {{ source('raw', 'medications') }}
