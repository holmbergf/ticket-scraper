{{ config(materialized='table') }}

-- One row per (source, event, crawl). Ingestion already lands one row per
-- natural key; this re-asserts the grain against the append-only raw zone
-- (prefer the latest import) and attaches the conformed match number.
with ranked as (
    select *,
        row_number() over (
            partition by source, event_id_external, crawl_ts_utc
            order by timestamp_imported desc
        ) as rn
    from {{ ref('stg_tickets_market_snapshots') }}
)

select
    s.source,
    s.event_id_external,
    e.match_number,
    e.match_key,
    s.crawl_ts_utc,
    cast(s.crawl_ts_utc as date) as crawl_date,
    s.event_url,
    s.lowest_price_cents,
    s.average_price_cents,
    s.highest_price_cents,
    s.inventory_count,
    s.lowest_price_includes_fees,
    s.listing_quality_label,
    s.price_refresh_ts_utc,
    s.timestamp_imported
from ranked s
left join {{ ref('clean_tickets_events') }} e
    on e.source = s.source and e.event_id_external = s.event_id_external
where s.rn = 1
