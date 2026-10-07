-- State codes are the two-letter values CMS publishes for states and territories.
select ccn
from {{ ref('stg_snf') }}
where state is null or length(state) <> 2
