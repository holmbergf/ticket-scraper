{{ config(materialized='table') }}

-- Per-match price change: daily best price on the first crawl date vs
-- the latest crawl date.
with daily_best as (
    select crawl_date, match_key, match_number, min(lowest_price_cents) as best_price_cents
    from {{ ref('fct_tickets_market_snapshots') }}
    where lowest_price_cents is not null
    group by 1, 2, 3
),

bounds as (
    select match_key, min(crawl_date) as first_date, max(crawl_date) as last_date
    from daily_best group by 1
)

select
    b.match_key,
    f.match_number,
    b.first_date as first_crawl_date,
    b.last_date as latest_crawl_date,
    f.best_price_cents as first_price_cents,
    l.best_price_cents as latest_price_cents,
    l.best_price_cents - f.best_price_cents as change_cents,
    case when f.best_price_cents > 0
         then round((l.best_price_cents - f.best_price_cents) * 100.0 / f.best_price_cents, 1)
         else 0 end as change_pct
from bounds b
join daily_best f on f.match_key = b.match_key and f.crawl_date = b.first_date
join daily_best l on l.match_key = b.match_key and l.crawl_date = b.last_date
