{{ config(materialized='table') }}

-- Per-crawl-date market benchmarks (port of analytics.get_market_benchmarks):
-- best (= cheapest across sources) price per match per day, then
-- min/median/avg/max over matches. Median is DuckDB's exact MEDIAN; the
-- legacy Python integer median could differ by one cent on even counts.
-- Deliberate correction vs legacy: benchmarks used to MIN over *every*
-- snapshot row including discovery-page teasers (e.g. StubHub grouping
-- pages repeat a featured $1,795 while the event page says $2,529), while
-- legacy latest-price surfaces used the event-page snapshot (MAX id).
-- Here daily best is over canonical per-crawl snapshots only, consistent
-- with every other surface (261 of 3,224 legacy game-days change).
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
