-- Staging patients must not carry direct identifiers forward.
select column_name
from information_schema.columns
where table_schema = 'staging'
  and table_name = 'stg_patients'
  and lower(column_name) in (
      'ssn', 'first', 'last', 'middle', 'address', 'passport', 'drivers', 'maiden', 'prefix', 'suffix'
  )
