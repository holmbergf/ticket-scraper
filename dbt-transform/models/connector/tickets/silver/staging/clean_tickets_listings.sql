{{ config(materialized='table') }}

-- Listings with bogus structural rows removed: Vivid Seats HTML contains
-- table scaffolding (section "categories", "Section Row Price…",
-- "Section Fees Incl") that the listing regex picks up.
select
    coalesce(e.collection_slug, nullif(l.collection_slug, ''), 'fifa-world-cup-2026') as collection_slug,
    coalesce(e.event_key, nullif(l.event_key, '')) as event_key,
    coalesce(e.event_uid, (coalesce(nullif(l.collection_slug, ''), 'fifa-world-cup-2026')
        || ':' || coalesce(nullif(l.event_key, ''), l.source || '-' || l.event_id_external))) as event_uid,
    l.source,
    l.event_id_external,
    e.match_number,
    e.match_key,
    l.crawl_ts_utc,
    cast(l.crawl_ts_utc as date) as crawl_date,
    l.listing_price_cents,
    l.section,
    l."row",
    l.deal_score,
    l.deal_label,
    l.notes,
    l.timestamp_imported
from {{ ref('stg_tickets_listings') }} l
left join {{ ref('clean_tickets_events') }} e
    on e.collection_slug = coalesce(nullif(l.collection_slug, ''), 'fifa-world-cup-2026')
   and e.source = l.source and e.event_id_external = l.event_id_external
where lower(coalesce(l.section, '')) not in ('categories', 'section fees incl')
  and coalesce(l.section, '') not like 'Section Row Price%'
