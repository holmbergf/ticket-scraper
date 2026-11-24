# Security policy

## Supported versions

Only the current `main` branch is supported.

## Reporting a vulnerability

Please do not open a public issue containing credentials, tokens, cookies,
or exploit details. Report privately through GitHub's
“Report a vulnerability” flow on this repository (Security tab →
Advisories), or contact the maintainer through their GitHub profile.

Operational notes for operators:

- The only long-lived credential in automation is an SSH deploy key
  scoped to the standalone dashboard repository, stored as the
  `TICKET_SCRAPER_DASHBOARD_DEPLOY_KEY` Actions secret.
- Never commit `.env`, browser profiles/cookies, GitHub tokens, or raw
  HTML snapshots. `data/raw_html/` is local debugging output and is
  gitignored.
- Rotate the deploy key immediately if a workflow log or fork may have
  exposed it.
