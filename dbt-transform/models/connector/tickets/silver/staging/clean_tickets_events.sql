{{ config(materialized='table') }}

-- Silver staging: all source-specific ugliness is resolved here. Raw
-- events are append-only across crawls, so first collapse to one row per
-- (source, event): prefer the most complete version, then the latest
-- import. Team/city/stage/
-- country canonicalisation goes through seed mappings; unmapped values
-- pass through visibly rather than being fuzzy-matched.
with ranked as (
    select *,
        (case when event_name is not null then 1 else 0 end
       + case when match_number is not null then 1 else 0 end
       + case when stage is not null then 1 else 0 end
       + case when team_1 is not null then 1 else 0 end
       + case when team_2 is not null then 1 else 0 end
       + case when event_start_local is not null then 1 else 0 end
       + case when venue_name is not null then 1 else 0 end
       + case when city is not null then 1 else 0 end) as completeness,
        row_number() over (
            partition by source, event_id_external
            order by completeness desc, timestamp_imported desc
        ) as rn
    from {{ ref('stg_tickets_events') }}
),

deduped as (select * from ranked where rn = 1),

-- Strip decoration the marketplaces bake into team strings:
-- "FIFA World Cup: Algeria", "Atlanta GA - Uzbekistan", trailing ")".
stripped as (
    select *,
        nullif(trim(regexp_replace(regexp_replace(
            regexp_replace(coalesce(team_1, ''), '(?i)^fifa world cup[: -]+', ''),
            '^[A-Za-z .-]+,?\s*[A-Z]{2}\s+-\s+', ''), '\)+$', '')), '') as team_1_cleaned,
        nullif(trim(regexp_replace(regexp_replace(
            regexp_replace(coalesce(team_2, ''), '(?i)^fifa world cup[: -]+', ''),
            '^[A-Za-z .-]+,?\s*[A-Z]{2}\s+-\s+', ''), '\)+$', '')), '') as team_2_cleaned
    from deduped
),

normalized as (
    select
        s.source,
        s.event_id_external,
        s.event_url,
        s.event_name,
        s.match_number,
        coalesce(sm.canonical_stage, nullif(trim(s.stage), '')) as stage,
        case when s.team_1_cleaned is null then null
             when regexp_matches(s.team_1_cleaned, '^(W\d+|[123][A-L]|TBD|\d[A-Z]/)') then 'TBD'
             else coalesce(t1.canonical_team, s.team_1_cleaned) end as team_1,
        case when s.team_2_cleaned is null then null
             when regexp_matches(s.team_2_cleaned, '^(W\d+|[123][A-L]|TBD|\d[A-Z]/)') then 'TBD'
             else coalesce(t2.canonical_team, s.team_2_cleaned) end as team_2,
        s.event_start_local,
        s.venue_name,
        coalesce(cm.canonical_city, s.city) as city,
        s.region,
        coalesce(com.canonical_country, s.country) as country,
        s.currency,
        s.completeness,
        s.timestamp_imported
    from stripped s
    left join {{ ref('team_mappings') }} t1 on lower(s.team_1_cleaned) = t1.raw_team
    left join {{ ref('team_mappings') }} t2 on lower(s.team_2_cleaned) = t2.raw_team
    left join {{ ref('city_mappings') }} cm on s.city = cm.raw_city
    left join {{ ref('stage_mappings') }} sm on lower(trim(s.stage)) = sm.raw_stage
    left join {{ ref('country_mappings') }} com on s.country = com.raw_country
)

select
    *,
    case
        when team_1 is not null and team_2 is not null and team_1 <> 'TBD' and team_2 <> 'TBD'
            then team_1 || ' vs ' || team_2 || coalesce(' (' || stage || ')', '')
        -- Knockout fixtures are listed before the teams are known. Name
        -- them by round and host city (e.g. "Quarter-Final — Seattle")
        -- rather than by an opaque match number. dim_tickets_matches adds
        -- the date when the same round/city hosts more than one match.
        when stage in ('Round of 32', 'Round of 16', 'Quarter-Final',
                       'Semi-Final', 'Bronze Final', 'Final')
             and city is not null
            then stage || ' — ' || city
        when match_number is not null
            then 'Match ' || match_number || coalesce(' (' || stage || ')', '')
        when event_name is not null
            then nullif(trim(regexp_replace(regexp_replace(regexp_replace(
                    event_name, '^[A-Za-z ]+(,\s*[A-Z]{2})?\s*-\s*', ''),
                    '\s*\|.*$', ''), 'Tickets$', '')), '')
        else 'Unknown'
    end as display_name,
    -- Cross-source key: match_number is populated for every source (104
    -- matches), so it is the conformed match identifier downstream.
    case when match_number is not null then 'match-' || match_number
         else source || '-' || event_id_external end as match_key
from normalized
