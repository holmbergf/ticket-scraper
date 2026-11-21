{{ config(materialized='table') }}

-- Listings with bogus structural rows removed: Vivid Seats HTML contains
-- table scaffolding (section "categories", "Section Row Price…",
-- "Section Fees Incl") that the listing regex picks up.
select
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
    on e.source = l.source and e.event_id_external = l.event_id_external
where lower(coalesce(l.section, '')) not in ('categories', 'section fees incl')
  and coalesce(l.section, '') not like 'Section Row Price%'
