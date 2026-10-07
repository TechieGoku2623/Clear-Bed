-- Real CMS facility attributes plus the synthetic acceptance profile.
-- capability_source documents that dialysis, trach, behavioral, bariatric,
-- and response hours are not CMS fields.
select
    s.ccn,
    s.facility_name,
    s.address,
    s.city,
    s.state,
    s.zip,
    s.certified_beds,
    s.avg_residents_per_day,
    s.overall_rating,
    s.health_inspection_rating,
    s.staffing_rating,
    s.provider_type,
    s.ownership_type,
    s.latitude,
    s.longitude,
    s.est_open_beds,
    s.accepts_medicaid,
    c.accepts_dialysis,
    c.accepts_trach_vent,
    c.accepts_behavioral,
    c.accepts_bariatric,
    c.typical_response_hours,
    c.capability_source
from {{ source('raw', 'cms_snf') }} as s
left join {{ source('raw', 'snf_capabilities_synthetic') }} as c
    on s.ccn = c.ccn
