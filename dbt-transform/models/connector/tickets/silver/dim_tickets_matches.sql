{{ config(materialized='table') }}

-- Conformed match dimension: one row per FIFA match (match_number 1..104).
-- The canonical row is picked from the most trustworthy event version:
-- known (non-TBD) teams first, then full-coverage sources (FIFA Collect /
-- Gametime list all 104 matches), then completeness.
with ranked as (
    select *,
        row_number() over (
            partition by match_number
            order by
                (team_1 is not null and team_2 is not null and team_1 <> 'TBD' and team_2 <> 'TBD') desc,
                case source
                    when 'fifacollect' then 1 when 'gametime' then 2
                    when 'vivid' then 3 when 'stubhub' then 4 else 5
                end,
                completeness desc,
                timestamp_imported desc
        ) as rn
    from {{ ref('clean_tickets_events') }}
    where match_number is not null
),

coverage as (
    select match_number,
           count(distinct source) as sources_tracking,
           count(*) as source_events
    from {{ ref('clean_tickets_events') }}
    where match_number is not null
    group by 1
)

select
    r.match_number,
    r.match_key,
    r.display_name,
    r.stage,
    r.team_1,
    r.team_2,
    r.event_start_local,
    cast(r.event_start_local as date) as match_date,
    r.venue_name,
    r.city,
    r.country,
    c.sources_tracking,
    c.source_events
from ranked r
join coverage c using (match_number)
where r.rn = 1
