{{ config(materialized='table') }}

-- One row per (collection, source, event, crawl). Ingestion already
-- lands one row per natural key; this re-asserts the grain against the
-- append-only raw zone (prefer the latest import) and attaches the
-- conformed canonical event identity.
with ranked as (
    select *,
        row_number() over (
            partition by coalesce(nullif(collection_slug, ''), 'fifa-world-cup-2026'),
                         source, event_id_external, crawl_ts_utc
            order by timestamp_imported desc
        ) as rn
    from {{ ref('stg_tickets_market_snapshots') }}
)

select
    coalesce(e.collection_slug, nullif(s.collection_slug, ''), 'fifa-world-cup-2026') as collection_slug,
    coalesce(e.event_key, nullif(s.event_key, '')) as event_key,
    coalesce(e.event_uid, (coalesce(nullif(s.collection_slug, ''), 'fifa-world-cup-2026')
        || ':' || coalesce(nullif(s.event_key, ''), s.source || '-' || s.event_id_external))) as event_uid,
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
    on e.collection_slug = coalesce(nullif(s.collection_slug, ''), 'fifa-world-cup-2026')
   and e.source = s.source and e.event_id_external = s.event_id_external
where s.rn = 1
