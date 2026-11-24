---
name: add-ticket-event
description: Add a game, tournament, or multi-session event to ticket-scraper end to end — collection config, live crawl, warehouse publish, workflow, and dashboard verification — from a plain-language request.
---

# Add Ticket Event

Use this skill when the user asks to add, track, stand up, or put a game,
tournament, or event on the dashboard — for example “Add Team A vs Team B
to our dashboard,” “track the Masters 2027,” or “add the <event> on
<date>.” Complete the setup end to end with minimal supervision: research
the fixture, create the collection, crawl it live, rebuild/publish the
warehouse, add its workflow, verify the dashboard, and push both repos.
Do not stop at a plan or a config file unless the user asked only to
investigate or draft.

## Operating rules

- Work in this repository. Read first: `README.md`,
  `collections/README.md`, `docs/architecture.md`, `AGENTS.md`, the two
  existing files in `collections/`, and the closest prior art for the
  sources involved. Existing behavior in code/tests is the contract.
- Never invent fixture facts, event URLs, source IDs, prices, or listings.
  Every URL/ID in a config must be found on the marketplace (or proven by
  a successful parser probe), and every landed price must come from a
  real crawl — never search-result snippets or sample data.
- Ask the user only for a genuine blocker: two or more plausible fixtures
  match the request (date/home team cannot be resolved), no configured
  marketplace lists the event, or a choice only they can make (API
  credentials, making data public). Otherwise decide and proceed.
- Manual ingestion only. Do not add schedules unless explicitly asked.
- Do not use CAPTCHA-solving services, proxy rotation, or account
  credentials to get past a bot wall. The supported escalations are the
  browser/session techniques below, running locally, or official APIs.
- Preserve all existing collections. A new collection must not change
  FIFA outputs except shared-code fixes that are tested against it.

## 1. Identify the fixture

1. Search existing state first: `collections/*.toml`,
   `ticket-ingest collections list`, and the published catalog
   (`data/data_warehouse/semantic/semantic_event_catalog.parquet`).
   If the event is already tracked, update/refresh that collection
   instead of creating a duplicate.
2. Establish the official facts from authoritative or marketplace
   sources: official name, participants in fixture order (away at home
   for US team sports), date, local start time and timezone, venue,
   city/region/country, stage/session/round, and currency.
3. Classify the request:
   - **Single game** (`kind = "game"`, one canonical event) — e.g. a
     named matchup on a date (or the next meeting if uniquely
     determined).
   - **Tournament** (`kind = "tournament"`) — many matches; declare
     canonical events only if a reliable fixture list is practical,
     otherwise let keys derive from sequence/participants/date discovered
     on listing pages.
   - **Multi-session event** (`kind = "event"`) — one canonical event per
     day/session/round (Masters Thu–Sun pattern in
     `collections/README.md`). Participants are optional.
4. Choose slugs:
   - Collection: league/context + fixture + date/year, lowercase hyphens
     (`nfl-cowboys-at-seahawks-2026-12-07`, `masters-2027`,
     `fifa-world-cup-2026`). Filename must equal the slug.
   - Event key: stable and human-readable
     (`dallas-cowboys-at-seattle-seahawks`, `thursday`, `match-<n>` only
     when deriving from sequence numbers).

## 2. Find marketplace access paths

Supported adapters live in `ticket_ingest/jobs.py` (`SOURCE_ADAPTERS`):
`gametime`, `vivid`, `stubhub`, `viagogo`, `fifacollect` (FIFA RTT only —
never add it to non-FIFA collections).

For each plausible marketplace, find the exact event (search the site /
web for the fixture, then confirm the page itself):

- Prefer **`event_urls` mode** for single games and small session sets:
  record the direct event URL and the source event ID it contains.
- Use **`discovery` mode** for tournaments: performer/category URL plus
  declared canonical events resolved by source ID, URL, participants +
  date, or `match_terms`. Verify discovery keeps only the intended
  events (exclude parking passes and unrelated fixtures).
- Viagogo usually shares StubHub event IDs: use its own verified event
  URL as `event_urls`, or `cross_source` + `event_url_template` only
  after proving the template resolves to this fixture.
- StubHub/Viagogo sit behind DataDome. The proven recipe is already in
  the fetch layer (installed Chrome channel, no pinned `Sec-Fetch-*`
  headers); add `warmup_urls` (home, then performer/category) for
  StubHub, because cold deep links get a CAPTCHA wall while a warmed
  session passes. If a page still returns the wall, follow the
  diagnosis notes in `docs/architecture.md` §3 before trying anything
  else.
- Gametime listings may render client-side: use
  `fetch_mode = "playwright"`, `event_scroll = true`, and
  `event_wait_selector = "[data-testid^='listing-card-']"` when the
  static HTML has no prices. Vivid Seats uses `fetch_mode = "browser"`.

Probe before committing to a source: fetch each candidate URL once with
the project's fetch functions/parsers (scratch scripts belong in `/tmp`)
and record status, parsed snapshot count, lowest price, and listing
count. A source with no verifiable priced snapshot does not go in the
config as “working” — either fix the generic parser/fetch path (with a
committed test) or leave the source out and report why.

## 3. Create the collection

Copy the closest file in `collections/` to `collections/<slug>.toml`.
Essentials (see existing files for exact syntax):

- Header: `slug`, `title`, `kind`, `status` (`active` unless the event
  has concluded), `description`, `timezone`, `icon`, `accent_color`.
- `[[events]]` per canonical event: `key`, `name`, `stage`, `sequence`,
  `participant_1/2`, `starts_at_local` (ISO, with offset), venue/city/
  region/country/currency, `match_terms`, and verified
  `source_event_ids`.
- `[sources.<name>]`: `mode`, URLs, `page_key = "<short-slug>"`,
  `fetch_mode`/workers/fetch controls from §2, and
  `expected_events` = how many canonical events that source lists.
- Optional `priority_participants` / `priority_stages` only when fetch
  ordering matters (large tournaments).

Then: `.venv/bin/ticket-ingest collections validate <slug>` and
`.venv/bin/ticket-ingest collections list`.

## 4. Test-crawl, then land real data

Activate the project env (`source .venv/bin/activate`); on this machine
resolve ordinary CA-bundle configuration for the environment if TLS validation fails; never disable certificate verification.

1. Scratch crawl, one source at a time:
   `ticket-ingest --data-dir /tmp/<slug>-data crawl --collection <slug> --source <source>`.
   Inspect landed Parquet (DuckDB): identity columns, snapshot price,
   listing counts. Prices must be plausible for the event (a parser
   picking a related-event or parking price is a parser bug — fix the
   generic parser/fetch path and add a test; never hand-edit data).
2. Real crawl of every configured source into `data/`:
   `ticket-ingest crawl --collection <slug>`.
   A source landing event rows without snapshots (WAF) is acceptable if
   reported; zero priced sources overall is not a completed setup —
   keep diagnosing or ask the user.
3. Rebuild and publish:
   `cd dbt-transform && RAW_BASE_PATH=../data dbt build --target prod --profiles-dir .`,
   then `python -m ticket_ingest.publish_warehouse`.
   Verify in `semantic_collections`, `semantic_event_catalog`, and
   `semantic_event_prices` that the new slug/events/prices are present
   and no other collection changed unexpectedly.

## 5. Workflow

Copy `.github/workflows/ingest-fifa-world-cup-2026.yml` to
`.github/workflows/ingest-<slug>.yml`; change only the workflow `name:`,
the `collection:` input, and the source choices to the collection's
configured sources. Validate YAML parses. After pushing, dispatch it
once (`gh workflow run ingest-<slug>.yml -f source=<one source>`) to
prove the hosted path, and read the logs — a green local crawl does not
prove the runner's IP/browser passes a WAF.

## 6. Dashboard verification

No dashboard code changes are expected: the sidebar **Tracking** switcher
lists collections from the published catalog, and Home/Market/Deals/
History render the selected one.

1. Run the standalone-shaped app locally
   (`streamlit run dashboard/streamlit_app.py`) and in a real browser
   check, for the new collection: Home card + table, **Market** (watch
   for null-inventory crashes), Deals, and History incl. listings
   labelled with the selected event. Flip to an existing collection and
   confirm it still renders.
2. Refresh the deployed app: run
   `./dashboard/export_standalone.sh <checkout of fholmberg/ticket-scraper-dashboard>`,
   verify that export standalone (AppTest or a fresh server), then commit
   and push it. If the live app still errors after the push, it needs
   **Manage app → Reboot app** in Streamlit Cloud — say so; do not claim
   the public URL updated until you have loaded it and seen the new
   collection.

## 7. Tests, docs, commits

- Update the exact-collection assertions in
  `data-integration/tests/test_collections.py` and
  `test_publish_catalog.py` for the new slug; add config/parser tests for
  any new generic behavior (never only a test that restates the fixture).
- Run: `pytest data-integration/tests dashboard/tests -q`,
  `RAW_BASE_PATH=tests/fixtures dbt build` and the prod build above.
- Update `collections/README.md` examples or `docs/architecture.md` only
  if the new collection changed a pattern; update the shipped-collections
  sentence in `README.md`.
- Commit the main repo (config, workflow, any generic code/tests, raw
  partitions + manifests, republished warehouse) and the standalone
  dashboard repo separately, then push both. On this machine the
  keychain holds the wrong GitHub account for each repo, so push with
  `git -c credential.helper= -c credential.helper='!gh auth git-credential' push`
  (using the standalone repository owner's configured GitHub credentials).
- Watch the pushed CI runs to green before reporting done.

## Report

State: the slug and canonical events added; per-source outcome (priced /
listings / blocked, with the cheapest price seen); warehouse/dashboard
verification performed; workflow file added and any hosted-run result;
commit hashes for both repos; and anything the user still must do in
Streamlit Cloud. Name every source that did not land prices and why —
silent gaps are worse than an honest partial setup.
