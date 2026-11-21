{{ config(materialized='view') }}

-- Semantic: one row per match at current prices, dollars. The dashboard's
-- "all games / best deals" surface. best/worst/spread are over per-source
-- lowest prices; savings_vs_worst is null for single-source matches.
with priced as (
    select * from {{ ref('fct_tickets_latest_prices') }}
    where lowest_price_cents is not null and match_number is not null
),

agg as (
    select
        match_number,
        min(lowest_price_cents) as best_cents,
        max(lowest_price_cents) as worst_cents,
        count(*) as sources_with_price,
        sum(inventory_count) as total_inventory,
        max(latest_crawl_ts_utc) as latest_crawl_ts_utc
    from priced group by 1
),

best_source as (
    select match_number, source as best_source
    from (
        select *, row_number() over (partition by match_number order by lowest_price_cents, source) as rn
        from priced
    ) where rn = 1
)

select
    d.match_number,
    d.match_key,
    d.display_name,
    d.stage,
    d.team_1,
    d.team_2,
    d.event_start_local,
    d.match_date,
    d.venue_name,
    d.city,
    d.country,
    d.sources_tracking,
    a.sources_with_price,
    round(a.best_cents / 100.0, 2) as best_price,
    b.best_source,
    round(a.worst_cents / 100.0, 2) as worst_price,
    case when a.sources_with_price >= 2 then round((a.worst_cents - a.best_cents) / 100.0, 2) end as savings_vs_worst,
    a.total_inventory,
    a.latest_crawl_ts_utc
from {{ ref('dim_tickets_matches') }} d
left join agg a using (match_number)
left join best_source b using (match_number)
