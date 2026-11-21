{{ config(materialized='view') }}

-- Bronze: 1:1 casts of the frozen raw listings schema.
with source as (
    select * from {{ raw_table('listings') }}
)

select
    source,
    event_id_external,
    cast(replace(crawl_ts_utc, 'Z', '') as timestamp) as crawl_ts_utc,
    cast(listing_price_cents as bigint) as listing_price_cents,
    section,
    "row",
    cast(deal_score as double) as deal_score,
    deal_label,
    notes,
    cast(replace(timestamp_imported, 'Z', '') as timestamp) as timestamp_imported
from source
