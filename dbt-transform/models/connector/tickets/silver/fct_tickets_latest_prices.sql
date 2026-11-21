{{ config(materialized='table') }}

-- Latest snapshot per (source, event) — the "current market" grain.
-- Includes events with no snapshot yet (null prices) so coverage gaps
-- stay visible.
with latest as (
    select *,
        row_number() over (
            partition by collection_slug, source, event_id_external
            order by crawl_ts_utc desc
        ) as rn
    from {{ ref('clean_tickets_market_snapshots') }}
)

select
    e.collection_slug,
    e.event_key,
    e.event_uid,
    e.source,
    e.event_id_external,
    e.event_url,
    e.event_name,
    e.display_name,
    e.match_number,
    e.match_key,
    e.stage,
    e.team_1,
    e.team_2,
    e.event_start_local,
    e.venue_name,
    e.city,
    e.country,
    e.currency,
    s.crawl_ts_utc as latest_crawl_ts_utc,
    s.lowest_price_cents,
    s.average_price_cents,
    s.highest_price_cents,
    s.inventory_count,
    s.lowest_price_includes_fees
from {{ ref('clean_tickets_events') }} e
left join latest s
    on s.collection_slug = e.collection_slug
   and s.source = e.source and s.event_id_external = e.event_id_external and s.rn = 1
