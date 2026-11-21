# dbt CI fixtures

Small coherent samples of the real raw partitions (matches 1, 2, 4; first
two and last crawl dates), written with the same content-addressed layout
as `data/raw`. CI points `RAW_BASE_PATH` here so the exact production dbt
models build with no credentials and no production data — the elt-pipeline
fixture convention. Regenerate with the script recorded in each manifest's
`source` field if raw schemas change.
