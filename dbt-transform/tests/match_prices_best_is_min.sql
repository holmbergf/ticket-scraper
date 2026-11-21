-- semantic_match_prices.best_price must be the minimum per-source latest
-- lowest price for the match, and best_source must actually offer it.
select m.match_number
from {{ ref('semantic_match_prices') }} m
join (
    select match_number, min(lowest_price_cents) as min_cents
    from {{ ref('fct_tickets_latest_prices') }}
    where lowest_price_cents is not null and match_number is not null
    group by 1
) x using (match_number)
where m.best_price is distinct from round(x.min_cents / 100.0, 2)
