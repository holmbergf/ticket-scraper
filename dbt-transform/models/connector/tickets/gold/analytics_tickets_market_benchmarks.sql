{{ config(materialized='table') }}

-- Per-crawl-date market benchmarks: best (= cheapest across sources)
-- price per match per day, then min/median/avg/max over matches. Daily
-- best is over canonical per-crawl snapshots only (event-page rows), so
-- discovery-page featured prices never set the market low.
with daily_best as (
    select
        crawl_date,
        match_key,
        min(lowest_price_cents) as best_price_cents,
        sum(inventory_count) as total_inventory
    from {{ ref('fct_tickets_market_snapshots') }}
    where lowest_price_cents is not null
    group by 1, 2
)

select
    crawl_date,
    min(best_price_cents) as min_price_cents,
    cast(median(best_price_cents) as bigint) as median_price_cents,
    cast(avg(best_price_cents) as bigint) as avg_price_cents,
    max(best_price_cents) as max_price_cents,
    count(*) as total_events,
    sum(total_inventory) as total_inventory
from daily_best
group by 1
