-- semantic_event_prices.best_price must be the minimum per-source latest
-- lowest price for the canonical event.
select m.collection_slug, m.event_uid
from {{ ref('semantic_event_prices') }} m
join (
    select collection_slug, event_uid, min(lowest_price_cents) as min_cents
    from {{ ref('fct_tickets_latest_prices') }}
    where lowest_price_cents is not null and event_uid is not null
    group by 1, 2
) x using (collection_slug, event_uid)
where m.best_price is distinct from round(x.min_cents / 100.0, 2)
