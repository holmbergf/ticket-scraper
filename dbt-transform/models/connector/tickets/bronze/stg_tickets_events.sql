{{ config(materialized='view') }}

-- Bronze: 1:1 casts of the frozen raw events schema. No joins, no
-- filtering: a raw schema break must fail in exactly one obvious place.
with source as (
    select * from {{ raw_table('events') }}
    union all by name
    -- Files written before collections existed lack these columns;
    -- this empty branch gives every generation one stable schema.
    select null::varchar as collection_slug, null::varchar as event_key where false
)

select
    collection_slug,
    event_key,
    source,
    event_id_external,
    event_url,
    event_name,
    cast(match_number as integer) as match_number,
    stage,
    team_1,
    team_2,
    cast(event_start_local as timestamp) as event_start_local,
    venue_name,
    city,
    region,
    country,
    currency,
    cast(replace(timestamp_imported, 'Z', '') as timestamp) as timestamp_imported
from source
