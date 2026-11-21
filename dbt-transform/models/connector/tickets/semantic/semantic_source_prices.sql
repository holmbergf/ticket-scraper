{{ config(materialized='view') }}

-- Semantic: latest price per (source, event) in dollars — the long-form
-- companion to semantic_match_prices (scatter plot, per-event drill-down).
select
    source,
    event_id_external,
    event_url,
    display_name,
    match_number,
    match_key,
    stage,
    team_1,
    team_2,
    event_start_local,
    venue_name,
    city,
    country,
    currency,
    round(lowest_price_cents / 100.0, 2) as lowest_price,
    round(average_price_cents / 100.0, 2) as average_price,
    round(highest_price_cents / 100.0, 2) as highest_price,
    inventory_count,
    lowest_price_includes_fees,
    latest_crawl_ts_utc as crawl_ts_utc
from {{ ref('fct_tickets_latest_prices') }}
