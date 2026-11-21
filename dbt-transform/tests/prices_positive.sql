-- Prices are integer cents > 0 wherever present (parsers store null for
-- "no price", never 0). A 0/negative price means a parser regression.
select source, event_id_external, crawl_ts_utc, lowest_price_cents
from {{ ref('fct_tickets_market_snapshots') }}
where lowest_price_cents <= 0 or average_price_cents < 0 or highest_price_cents < 0
   or (lowest_price_cents is not null and highest_price_cents is not null
       and highest_price_cents < lowest_price_cents)
