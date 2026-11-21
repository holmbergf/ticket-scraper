-- Display names are the dashboard's match labels (pickers, tables, chart
-- legends), so two matches must never share one. Knockout matches are
-- named by round + city, which can repeat; the dimension adds the date
-- in that case. This test fails if that disambiguation regresses.
select display_name, count(*) as matches
from {{ ref('dim_tickets_matches') }}
group by display_name
having count(*) > 1
