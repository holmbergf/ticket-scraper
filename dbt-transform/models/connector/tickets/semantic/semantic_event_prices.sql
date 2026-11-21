{{ config(materialized='view') }}

-- Semantic: one row per canonical event at current prices, dollars.
-- best/worst/spread are over per-source lowest prices;
-- savings_vs_worst is null for single-source events.
with priced as (
    select * from {{ ref('fct_tickets_latest_prices') }}
    where lowest_price_cents is not null and event_key is not null
),

agg as (
    select
        collection_slug,
        event_uid,
        min(lowest_price_cents) as best_cents,
        max(lowest_price_cents) as worst_cents,
        count(*) as sources_with_price,
        sum(inventory_count) as total_inventory,
        max(latest_crawl_ts_utc) as latest_crawl_ts_utc
    from priced group by 1, 2
),

best_source as (
    select collection_slug, event_uid, source as best_source
    from (
        select *, row_number() over (
            partition by collection_slug, event_uid
            order by lowest_price_cents, source) as rn
        from priced
    ) where rn = 1
)

select
    d.collection_slug,
    d.event_key,
    d.event_uid,
    d.match_number,
    d.match_key,
    d.display_name,
    d.stage,
    d.team_1,
    d.team_2,
    d.participant_1,
    d.participant_2,
    d.event_start_local,
    d.event_date,
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
from {{ ref('dim_tickets_events') }} d
left join agg a using (collection_slug, event_uid)
left join best_source b using (collection_slug, event_uid)
