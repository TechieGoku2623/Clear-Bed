-- The model matrix must not contain outcome columns.
select column_name
from information_schema.columns
where table_schema = 'marts'
  and table_name = 'feat_admission_snapshot'
  and lower(column_name) in (
      'los_days', 'stop_ts', 'avoidable_days', 'is_stuck', 'barrier_type', 'deathdate'
  )
