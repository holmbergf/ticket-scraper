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
),

chosen as (
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
        c.source_events,
        count(*) over (partition by r.display_name) as display_name_count
    from ranked r
    join coverage c using (match_number)
    where r.rn = 1
)

select
    match_number,
    match_key,
    -- A round/city label can describe two matches (e.g. two Round of 32
    -- games in Dallas). Add the match date only where needed to keep the
    -- human-readable labels unambiguous.
    case
        when display_name_count > 1 and match_date is not null
            then display_name || ' · ' || strftime(match_date, '%b %d')
        else display_name
    end as display_name,
    stage,
    team_1,
    team_2,
    event_start_local,
    match_date,
    venue_name,
    city,
    country,
    sources_tracking,
    source_events
from chosen
