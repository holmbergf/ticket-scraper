{{ config(materialized='table') }}

-- Per-event price change: daily best price on the first crawl date vs
-- the latest crawl date, within each collection.
with daily_best as (
    select collection_slug, crawl_date, event_uid, event_key, match_number, match_key,
           min(lowest_price_cents) as best_price_cents
    from {{ ref('fct_tickets_market_snapshots') }}
    where lowest_price_cents is not null
    group by 1, 2, 3, 4, 5, 6
),

bounds as (
    select collection_slug, event_uid, min(crawl_date) as first_date, max(crawl_date) as last_date
    from daily_best group by 1, 2
)

select
    b.collection_slug,
    b.event_uid,
    f.event_key,
    f.match_key,
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
join daily_best f
  on f.collection_slug = b.collection_slug and f.event_uid = b.event_uid and f.crawl_date = b.first_date
join daily_best l
  on l.collection_slug = b.collection_slug and l.event_uid = b.event_uid and l.crawl_date = b.last_date
