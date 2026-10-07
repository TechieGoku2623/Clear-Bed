-- One row per inpatient encounter. lives_alone_proxy is a seeded synthetic
-- stand-in. Synthea does not chart household composition.
with encounters as (
    select * from {{ ref('stg_encounters') }}
),
inpatient as (
    select
        e.encounter_id as stay_id,
        e.patient_id,
        e.start_ts as admit_ts,
        e.stop_ts,
        greatest(date_diff('day', cast(e.start_ts as date), cast(e.stop_ts as date)), 0) as los_days,
        isodow(e.start_ts) as admit_dow,
        month(e.start_ts) as admit_month,
        e.organization_id,
        e.payer_id,
        e.total_cost,
        e.reason_code,
        e.reason_description,
        e.code as encounter_code,
        e.description as encounter_description
    from encounters as e
    where e.encounter_class = 'inpatient'
      and e.start_ts is not null
      and e.stop_ts is not null
),
patients as (
    select * from {{ ref('stg_patients') }}
),
payers as (
    select * from {{ ref('stg_payers') }}
),
rules as (
    select * from {{ ref('condition_groups') }}
),
condition_hits as (
    select
        c.patient_id,
        c.encounter_id,
        c.start_ts,
        c.stop_ts,
        c.code,
        c.description,
        r.condition_group,
        r.priority
    from {{ ref('stg_conditions') }} as c
    inner join rules as r
        on (
            (r.match_type = 'code' and c.code = r.match_value)
            or (
                r.match_type = 'description'
                and c.description is not null
                and position(lower(r.match_value) in lower(c.description)) > 0
            )
        )
),
condition_best as (
    select patient_id, encounter_id, start_ts, stop_ts, code, description, condition_group
    from (
        select
            *,
            row_number() over (
                partition by patient_id, encounter_id, code, description, start_ts
                order by priority
            ) as rn
        from condition_hits
    ) as ranked
    where rn = 1
),
reason_group as (
    select
        i.stay_id,
        coalesce(
            (
                select r.condition_group
                from rules as r
                where r.match_type = 'code' and r.match_value = i.reason_code
                order by r.priority
                limit 1
            ),
            (
                select r.condition_group
                from rules as r
                where
                    r.match_type = 'description'
                    and i.reason_description is not null
                    and position(lower(r.match_value) in lower(i.reason_description)) > 0
                order by r.priority
                limit 1
            )
        ) as condition_group
    from inpatient as i
),
encounter_group as (
    select
        i.stay_id,
        (
            select b.condition_group
            from condition_best as b
            where b.encounter_id = i.stay_id
            order by
                case b.condition_group
                    when 'sepsis' then 10
                    when 'stroke' then 20
                    when 'hip_fracture' then 30
                    when 'pneumonia' then 40
                    when 'heart_failure' then 50
                    else 100
                end
            limit 1
        ) as condition_group
    from inpatient as i
),
flags as (
    select
        i.stay_id,
        max(case when b.condition_group = 'dementia' then 1 else 0 end) as flag_dementia,
        max(case when b.condition_group = 'ckd' then 1 else 0 end) as flag_ckd_dialysis,
        max(case when b.condition_group = 'copd' then 1 else 0 end) as flag_copd,
        max(case when b.condition_group = 'heart_failure' then 1 else 0 end) as flag_chf,
        max(case when b.condition_group = 'obesity' then 1 else 0 end) as flag_obesity,
        max(case when b.condition_group = 'behavioral' then 1 else 0 end) as flag_behavioral,
        max(case when b.condition_group = 'substance' then 1 else 0 end) as flag_substance
    from inpatient as i
    left join condition_best as b
        on b.patient_id = i.patient_id
        and (b.start_ts is null or b.start_ts <= i.admit_ts)
        and (b.stop_ts is null or b.stop_ts >= i.admit_ts)
    group by i.stay_id
),
oxygen as (
    select
        i.stay_id,
        max(
            case
                when
                    lower(coalesce(m.description, '')) like '%oxygen%'
                    or lower(coalesce(pr.description, '')) like '%oxygen%'
                    then 1
                else 0
            end
        ) as flag_home_o2
    from inpatient as i
    left join {{ ref('stg_medications') }} as m
        on m.patient_id = i.patient_id
        and (m.start_ts is null or m.start_ts <= i.admit_ts)
        and (m.stop_ts is null or m.stop_ts >= i.admit_ts)
    left join {{ ref('stg_procedures') }} as pr
        on pr.patient_id = i.patient_id
        and pr.start_ts <= i.admit_ts + interval 2 day
        and pr.start_ts >= i.admit_ts - interval 1 day
    group by i.stay_id
),
med_counts as (
    select
        i.stay_id,
        count(distinct m.code) as n_active_meds
    from inpatient as i
    left join {{ ref('stg_medications') }} as m
        on m.patient_id = i.patient_id
        and m.code is not null
        and m.code <> ''
        and (m.start_ts is null or m.start_ts <= i.admit_ts)
        and (m.stop_ts is null or m.stop_ts >= i.admit_ts)
    group by i.stay_id
),
prior_ip as (
    select
        i.stay_id,
        count(distinct p.encounter_id) as prior_admits_12m
    from inpatient as i
    left join encounters as p
        on p.patient_id = i.patient_id
        and p.encounter_class = 'inpatient'
        and p.start_ts < i.admit_ts
        and p.start_ts >= i.admit_ts - interval 12 month
    group by i.stay_id
),
prior_ed as (
    select
        i.stay_id,
        count(distinct p.encounter_id) as prior_ed_visits_12m
    from inpatient as i
    left join encounters as p
        on p.patient_id = i.patient_id
        and p.encounter_class = 'emergency'
        and p.start_ts < i.admit_ts
        and p.start_ts >= i.admit_ts - interval 12 month
    group by i.stay_id
),
next_enc as (
    select stay_id, next_encounter_class
    from (
        select
            i.stay_id,
            n.encounter_class as next_encounter_class,
            row_number() over (partition by i.stay_id order by n.start_ts) as rn
        from inpatient as i
        inner join encounters as n
            on n.patient_id = i.patient_id
            and n.encounter_id <> i.stay_id
            and n.start_ts >= i.stop_ts
            and n.start_ts <= i.stop_ts + interval 3 day
    ) as ordered
    where rn = 1
)
select
    i.stay_id,
    i.patient_id,
    i.admit_ts,
    i.stop_ts,
    i.los_days,
    i.admit_dow,
    i.admit_month,
    date_diff('year', p.birthdate, cast(i.admit_ts as date)) as age_at_admit,
    case
        when date_diff('year', p.birthdate, cast(i.admit_ts as date)) < 18 then '0-17'
        when date_diff('year', p.birthdate, cast(i.admit_ts as date)) < 45 then '18-44'
        when date_diff('year', p.birthdate, cast(i.admit_ts as date)) < 65 then '45-64'
        when date_diff('year', p.birthdate, cast(i.admit_ts as date)) < 75 then '65-74'
        when date_diff('year', p.birthdate, cast(i.admit_ts as date)) < 85 then '75-84'
        else '85+'
    end as age_band,
    p.gender,
    p.race,
    p.ethnicity,
    p.zip,
    p.county,
    i.organization_id,
    i.payer_id,
    py.payer_name,
    case
        when lower(coalesce(py.payer_name, '')) like '%dual%' then 'dual'
        when
            lower(coalesce(py.payer_name, '')) like '%medicare%'
            and lower(py.payer_name) like '%medicaid%'
            then 'dual'
        when lower(coalesce(py.payer_name, '')) like '%medicare%' then 'medicare'
        when lower(coalesce(py.payer_name, '')) like '%medicaid%' then 'medicaid'
        when
            py.payer_name is null
            or lower(py.payer_name) in ('no_insurance', 'no insurance', 'uninsured')
            then 'none'
        else 'commercial'
    end as payer_type,
    coalesce(rg.condition_group, eg.condition_group, 'other') as condition_group,
    i.reason_code as primary_condition_code,
    i.reason_description as primary_condition_description,
    coalesce(ip.prior_admits_12m, 0) as prior_admits_12m,
    coalesce(ed.prior_ed_visits_12m, 0) as prior_ed_visits_12m,
    coalesce(mc.n_active_meds, 0) as n_active_meds,
    coalesce(f.flag_dementia, 0) as flag_dementia,
    coalesce(f.flag_ckd_dialysis, 0) as flag_ckd_dialysis,
    coalesce(f.flag_copd, 0) as flag_copd,
    coalesce(f.flag_chf, 0) as flag_chf,
    coalesce(f.flag_obesity, 0) as flag_obesity,
    coalesce(f.flag_behavioral, 0) as flag_behavioral,
    coalesce(f.flag_substance, 0) as flag_substance,
    coalesce(ox.flag_home_o2, 0) as flag_home_o2,
    case when (hash(i.patient_id) % 100) < 30 then 1 else 0 end as lives_alone_proxy,
    nx.next_encounter_class,
    i.total_cost
from inpatient as i
inner join patients as p on i.patient_id = p.patient_id
left join payers as py on i.payer_id = py.payer_id
left join reason_group as rg on i.stay_id = rg.stay_id
left join encounter_group as eg on i.stay_id = eg.stay_id
left join flags as f on i.stay_id = f.stay_id
left join oxygen as ox on i.stay_id = ox.stay_id
left join med_counts as mc on i.stay_id = mc.stay_id
left join prior_ip as ip on i.stay_id = ip.stay_id
left join prior_ed as ed on i.stay_id = ed.stay_id
left join next_enc as nx on i.stay_id = nx.stay_id
