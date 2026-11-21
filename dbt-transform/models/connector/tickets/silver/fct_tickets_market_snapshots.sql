{{ config(materialized='table') }}

-- Snapshot-grain fact (integer cents): every crawl observation of every
-- source event, keyed to the conformed canonical event. Derived and
-- disposable — rebuildable from the raw zone at any time.
select
    collection_slug,
    event_key,
    event_uid,
    source,
    event_id_external,
    match_number,
    match_key,
    crawl_ts_utc,
    crawl_date,
    event_url,
    lowest_price_cents,
    average_price_cents,
    highest_price_cents,
    inventory_count,
    lowest_price_includes_fees,
    listing_quality_label,
    price_refresh_ts_utc
from {{ ref('clean_tickets_market_snapshots') }}
