-- On a full warehouse, every barrier should land between 3% and 60%.
-- Tiny fixtures skip the check so CI can build without 500 stays.
with expected as (
    select * from (
        values
        ('post_acute_placement'),
        ('payer_pending'),
        ('guardianship_capacity'),
        ('home_services'),
        ('none')
    ) as v (barrier_type)
),
counts as (
    select barrier_type, count(*) as n
    from {{ ref('fct_stay_labels') }}
    group by barrier_type
),
total as (
    select count(*) as n from {{ ref('fct_stay_labels') }}
)
select
    e.barrier_type,
    coalesce(c.n, 0) as n,
    coalesce(c.n, 0) * 1.0 / t.n as pct
from expected as e
cross join total as t
left join counts as c on e.barrier_type = c.barrier_type
where t.n >= 500
  and (
      coalesce(c.n, 0) * 1.0 / t.n < 0.03
      or coalesce(c.n, 0) * 1.0 / t.n > 0.60
  )
