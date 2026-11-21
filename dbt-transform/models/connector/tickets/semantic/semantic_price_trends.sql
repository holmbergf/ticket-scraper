{{ config(materialized='view') }}

-- Semantic: full price history per (source, event) in dollars, for trend
-- charts.
select
    f.source,
    f.event_id_external,
    f.match_number,
    f.match_key,
    e.display_name,
    f.crawl_ts_utc,
    f.crawl_date,
    round(f.lowest_price_cents / 100.0, 2) as lowest_price,
    round(f.average_price_cents / 100.0, 2) as average_price,
    round(f.highest_price_cents / 100.0, 2) as highest_price,
    f.inventory_count
from {{ ref('fct_tickets_market_snapshots') }} f
left join {{ ref('clean_tickets_events') }} e
    on e.source = f.source and e.event_id_external = f.event_id_external
