# Collections

One TOML file per tracked collection. A collection is the unit that gets
its own crawl runs, workflow, and dashboard section: a tournament
(`fifa-world-cup-2026.toml`, 104 matches), a single game
(`nfl-cowboys-at-seahawks-2026-12-07.toml`), or a multi-session event
(one canonical event per day/session).

## Standing up a new collection

1. Copy the closest existing file and rename it to the new slug
   (filename must equal `slug`).
2. Declare each canonical event under `[[events]]` — or omit the section
   and let event keys derive from match numbers / participants / dates
   discovered on listing pages (how the World Cup collection works).
3. Configure each marketplace under `[sources.<name>]`:
   - `mode = "discovery"` + `discovery_url` — crawl a performer/category
     page and keep events that resolve to declared canonical events
     (by source id, URL, participants + date, or `match_terms`).
   - `mode = "event_urls"` + `[[sources.<name>.event_urls]]` — fetch
     declared event pages directly (best for one-off games).
   - `mode = "cross_source"` + `event_url_template` — build event URLs
     from another source's ids (Viagogo from StubHub).
   Optional per-source fetch controls: `fetch_mode`, `event_scroll`,
   `event_wait_selector` (wait for client-rendered listings), and
   `warmup_urls` (entry pages visited once per session before event
   pages — required where a WAF walls cold deep links, e.g. StubHub).
4. Validate and crawl:
   `ticket-ingest collections validate <slug>` then
   `ticket-ingest crawl --collection <slug>`.
5. Rebuild + publish (`dbt build --target prod`,
   `python -m ticket_ingest.publish_warehouse`). The dashboard picks the
   collection and its per-event pages up from the published catalog —
   no dashboard code changes.
6. To run it in GitHub Actions, copy an existing
   `.github/workflows/ingest-<slug>.yml` caller and change the
   `collection:` input.

Example: the Masters 2027 would be one collection
(`masters-2027.toml`, kind `event`) with four `[[events]]`
(`thursday` … `sunday`, stage `Round 1` … `Final Round`, venue
Augusta National) and per-source event URLs or a discovery URL per
marketplace. Participants are optional — events without two sides
render by name/stage instead of a team-vs-team header.
