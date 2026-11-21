{{ config(materialized='table') }}

-- Listings from the latest crawl per (source, event) only — the published
-- serving slice for the dashboard's listing-distribution drill-down. Full
-- listing history stays in the raw zone (and clean_tickets_listings);
-- publishing all ~600k rows would bloat the warehouse zone for no reader.
with latest_crawl as (
    select source, event_id_external, max(crawl_ts_utc) as crawl_ts_utc
    from {{ ref('clean_tickets_listings') }}
    group by 1, 2
)

select l.*
from {{ ref('clean_tickets_listings') }} l
join latest_crawl c
    on c.source = l.source
   and c.event_id_external = l.event_id_external
   and c.crawl_ts_utc = l.crawl_ts_utc
