-- fct_tickets_latest_prices grain + freshness: one row per (source, event)
-- and its crawl must be that event's max snapshot crawl.
select l.source, l.event_id_external
from {{ ref('fct_tickets_latest_prices') }} l
join (
    select source, event_id_external, max(crawl_ts_utc) as max_crawl, count(distinct crawl_ts_utc) as crawls
    from {{ ref('fct_tickets_market_snapshots') }} group by 1, 2
) m on m.source = l.source and m.event_id_external = l.event_id_external
where l.latest_crawl_ts_utc is distinct from m.max_crawl

union all

select source, event_id_external
from {{ ref('fct_tickets_latest_prices') }}
group by 1, 2
having count(*) > 1
