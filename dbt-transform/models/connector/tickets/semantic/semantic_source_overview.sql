{{ config(materialized='view') }}

-- Semantic: per-collection, per-source current-market overview in dollars.
select
    collection_slug,
    source,
    total_events,
    events_with_price,
    round(min_price_cents / 100.0, 2) as min_price,
    round(median_price_cents / 100.0, 2) as median_price,
    round(avg_price_cents / 100.0, 2) as avg_price,
    round(max_price_cents / 100.0, 2) as max_price,
    total_inventory,
    last_crawl_ts_utc
from {{ ref('analytics_tickets_source_overviews') }}
