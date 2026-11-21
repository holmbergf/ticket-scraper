{# Raw relation: the partitioned Parquet raw zone written by ticket-ingest.
   RAW_BASE_PATH points at the data dir holding raw/<dataset>/... — the repo
   data/ dir in dev/prod, tests/fixtures in CI. Bronze models never
   hard-code a location, so CI runs the exact production models against the
   committed mock fixtures with no credentials (elt-pipeline convention). #}
{% macro raw_table(dataset) %}
  (select * from read_parquet('{{ env_var('RAW_BASE_PATH', '../data') }}/raw/{{ dataset }}/**/*.parquet', hive_partitioning=true, union_by_name=true))
{% endmacro %}
