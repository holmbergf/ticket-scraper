# Data provenance and terms

The MIT `LICENSE` covers this repository's code and documentation. This
note covers the committed data files.

## What the data is

Files under `data/` are factual observations collected by this project's
crawlers from public resale-marketplace pages: event metadata, lowest /
average / highest asking prices, listing sections/rows/prices, inventory
counts where a source exposes them, and the UTC time each observation was
made. Prices are stored as integer cents in the raw, silver, and gold
zones and converted to dollars only in the semantic layer.

Current coverage and collection definitions are declared in
`collections/*.toml`; each Parquet row carries `collection_slug` and
`event_key`, and each run writes a JSON manifest under
`data/_manifests/` recording row counts, files, sources, and covered
crawl timestamps.

## Limitations

- Asking prices are point-in-time observations, not transaction prices,
  quotes, or guarantees of availability. Fees are included only where a
  source indicates that its displayed price includes them.
- Coverage is uneven: marketplaces list different events, expose
  different listing depth, and sometimes block automated access. A
  missing source or day means "not observed," not "not for sale."
- Canonical event matching is configuration- and parser-based; errors are
  possible. Derived warehouse files can always be rebuilt from `data/raw/`.
- Historical FIFA rows were imported from an earlier SQLite store and
  retain their original crawl timestamps.

## Reuse

You may reuse the committed factual price observations for research and
personal projects with attribution to this repository. No rights are
granted in any third party's trademarks, branding, page designs, or other
content. Test fixtures are small synthetic excerpts written for this
project; full marketplace page captures are intentionally not committed.

Anyone re-running the crawlers is responsible for complying with each
marketplace's terms, robots directives, rate limits, and applicable law.
This project is an independent research tool and is not affiliated with
FIFA, the NFL, Augusta National Golf Club, or any ticket marketplace.

Corrections: open a GitHub issue with the collection slug, event key,
source, and crawl timestamp involved.
