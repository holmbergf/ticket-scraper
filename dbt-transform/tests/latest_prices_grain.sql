-- fct_tickets_latest_prices grain + freshness: one row per
-- (collection, source, event), at that event's max snapshot crawl.
select l.collection_slug, l.source, l.event_id_external
from {{ ref('fct_tickets_latest_prices') }} l
join (
    select collection_slug, source, event_id_external,
           max(crawl_ts_utc) as max_crawl
    from {{ ref('fct_tickets_market_snapshots') }} group by 1, 2, 3
) m on m.collection_slug = l.collection_slug
   and m.source = l.source and m.event_id_external = l.event_id_external
where l.latest_crawl_ts_utc is distinct from m.max_crawl

union all

select collection_slug, source, event_id_external
from {{ ref('fct_tickets_latest_prices') }}
group by 1, 2, 3
having count(*) > 1
