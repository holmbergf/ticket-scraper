-- clean_tickets_events must be one row per (source, event): the append-only
-- raw zone carries one events version per crawl, and silver staging owns
-- the collapse. A duplicate here fans out every fact join downstream.
select source, event_id_external, count(*) as n
from {{ ref('clean_tickets_events') }}
group by 1, 2
having count(*) > 1
