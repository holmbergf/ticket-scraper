{{ config(materialized='view') }}

-- Semantic: latest price per (collection, source, event) in dollars —
-- the long-form companion to semantic_event_prices.
select
    f.collection_slug,
    f.event_key,
    f.event_uid,
    f.source,
    f.event_id_external,
    f.event_url,
    coalesce(d.display_name, f.display_name) as display_name,
    f.match_number,
    f.match_key,
    f.stage,
    f.team_1,
    f.team_2,
    f.event_start_local,
    f.venue_name,
    f.city,
    f.country,
    f.currency,
    round(f.lowest_price_cents / 100.0, 2) as lowest_price,
    round(f.average_price_cents / 100.0, 2) as average_price,
    round(f.highest_price_cents / 100.0, 2) as highest_price,
    f.inventory_count,
    f.lowest_price_includes_fees,
    f.latest_crawl_ts_utc as crawl_ts_utc
from {{ ref('fct_tickets_latest_prices') }} f
left join {{ ref('dim_tickets_events') }} d using (collection_slug, event_uid)
