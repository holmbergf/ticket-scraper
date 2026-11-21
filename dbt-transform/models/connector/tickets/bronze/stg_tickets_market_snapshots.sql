{{ config(materialized='view') }}

-- Bronze: 1:1 casts of the frozen raw market_snapshots schema.
-- Prices stay integer cents through silver/gold; only semantic converts.
with source as (
    select * from {{ raw_table('market_snapshots') }}
)

select
    source,
    event_id_external,
    cast(replace(crawl_ts_utc, 'Z', '') as timestamp) as crawl_ts_utc,
    event_url,
    cast(lowest_price_cents as bigint) as lowest_price_cents,
    cast(average_price_cents as bigint) as average_price_cents,
    cast(highest_price_cents as bigint) as highest_price_cents,
    cast(inventory_count as bigint) as inventory_count,
    cast(lowest_price_includes_fees as boolean) as lowest_price_includes_fees,
    listing_quality_label,
    cast(replace(price_refresh_ts_utc, 'Z', '') as timestamp) as price_refresh_ts_utc,
    cast(replace(timestamp_imported, 'Z', '') as timestamp) as timestamp_imported
from source
