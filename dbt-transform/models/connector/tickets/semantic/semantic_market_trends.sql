{{ config(materialized='view') }}

-- Semantic: daily per-collection market benchmarks in dollars.
select
    collection_slug,
    crawl_date,
    round(min_price_cents / 100.0, 2) as min_price,
    round(median_price_cents / 100.0, 2) as median_price,
    round(avg_price_cents / 100.0, 2) as avg_price,
    round(max_price_cents / 100.0, 2) as max_price,
    total_events,
    total_inventory
from {{ ref('analytics_tickets_market_benchmarks') }}
