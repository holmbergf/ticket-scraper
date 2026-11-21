{{ config(materialized='table') }}

-- Conformed event dimension: one row per canonical event in a collection
-- (collection_slug, event_key). The canonical row is picked from the most
-- trustworthy source-event version: known participants first, then source
-- priority, then completeness.
with ranked as (
    select *,
        row_number() over (
            partition by collection_slug, event_key
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
    where event_key is not null
),

coverage as (
    select collection_slug, event_key,
           count(distinct source) as sources_tracking,
           count(*) as source_events
    from {{ ref('clean_tickets_events') }}
    where event_key is not null
    group by 1, 2
),

chosen as (
    select
        r.collection_slug,
        r.event_key,
        r.event_uid,
        r.match_number,
        r.match_key,
        r.display_name,
        r.stage,
        r.team_1,
        r.team_2,
        r.event_start_local,
        cast(r.event_start_local as date) as event_date,
        r.venue_name,
        r.city,
        r.country,
        c.sources_tracking,
        c.source_events,
        count(*) over (partition by r.collection_slug, r.display_name) as display_name_count
    from ranked r
    join coverage c using (collection_slug, event_key)
    where r.rn = 1
)

select
    collection_slug,
    event_key,
    event_uid,
    match_number,
    match_key,
    -- A round/session + city label can describe two events in one
    -- collection. Add the date only where needed to keep labels unique.
    case
        when display_name_count > 1 and event_date is not null
            then display_name || ' · ' || strftime(event_date, '%b %d')
        else display_name
    end as display_name,
    stage,
    team_1,
    team_2,
    -- Generic participant aliases (team sports use team_1/team_2).
    team_1 as participant_1,
    team_2 as participant_2,
    event_start_local,
    event_date,
    event_date as match_date,
    venue_name,
    city,
    country,
    sources_tracking,
    source_events
from chosen
