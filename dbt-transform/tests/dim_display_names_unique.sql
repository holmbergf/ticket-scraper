-- Display names are the dashboard's event labels and page titles, so two
-- events in a collection must never share one. Stage/session + city labels
-- can repeat; the dimension adds the date in that case.
select collection_slug, display_name, count(*) as events
from {{ ref('dim_tickets_events') }}
group by 1, 2
having count(*) > 1
