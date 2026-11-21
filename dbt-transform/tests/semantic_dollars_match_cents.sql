-- Semantic dollars must equal silver cents / 100: cents->dollars conversion
-- exists in exactly one layer, and this pins it.
select s.collection_slug, s.source, s.event_id_external
from {{ ref('semantic_source_prices') }} s
join {{ ref('fct_tickets_latest_prices') }} f
    on f.collection_slug = s.collection_slug
   and f.source = s.source and f.event_id_external = s.event_id_external
where s.lowest_price is distinct from round(f.lowest_price_cents / 100.0, 2)
