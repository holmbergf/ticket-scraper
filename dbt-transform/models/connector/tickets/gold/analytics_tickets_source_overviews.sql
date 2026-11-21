{{ config(materialized='table') }}

-- Per-source current-market overview.
select
    source,
    count(*) as total_events,
    count(lowest_price_cents) as events_with_price,
    min(lowest_price_cents) as min_price_cents,
    cast(median(lowest_price_cents) as bigint) as median_price_cents,
    cast(avg(lowest_price_cents) as bigint) as avg_price_cents,
    max(lowest_price_cents) as max_price_cents,
    sum(inventory_count) as total_inventory,
    max(latest_crawl_ts_utc) as last_crawl_ts_utc
from {{ ref('fct_tickets_latest_prices') }}
group by 1
