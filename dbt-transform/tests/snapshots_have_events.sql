-- Join coverage: every priced snapshot must resolve to a clean event and
-- a canonical event_uid. An unmatched snapshot is invisible in every
-- cross-source surface, so coverage loss fails loudly.
select f.collection_slug, f.source, f.event_id_external, count(*) as orphan_snapshots
from {{ ref('fct_tickets_market_snapshots') }} f
left join {{ ref('clean_tickets_events') }} e
    on e.collection_slug = f.collection_slug
   and e.source = f.source and e.event_id_external = f.event_id_external
where e.event_id_external is null or f.event_uid is null
group by 1, 2, 3
