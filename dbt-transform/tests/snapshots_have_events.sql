-- Join coverage: every priced snapshot must resolve to a clean event (and a
-- match number). An unmatched snapshot is invisible in every cross-source
-- surface, so any coverage loss fails loudly instead of dropping silently.
select f.source, f.event_id_external, count(*) as orphan_snapshots
from {{ ref('fct_tickets_market_snapshots') }} f
left join {{ ref('clean_tickets_events') }} e
    on e.source = f.source and e.event_id_external = f.event_id_external
where e.event_id_external is null or f.match_number is null
group by 1, 2
