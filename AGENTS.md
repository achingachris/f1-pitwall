# AGENTS.md

Project-specific guidance for Codex sessions in this repo.

## What this is

**Greedy Boole** — Django 5 + HTMX monolith for F1 stats. jolpica is the only
data source in v1; FastF1 telemetry is deferred to v2. Deployed via
docker-compose (`web`, `worker`, `beat`, `postgres`, `redis`) behind Nginx +
Certbot, same flow as the user's other apps.

## Repo conventions

### Default Django scaffolding stays

Every app under this repo keeps the full `startapp` "batteries-included"
layout — `apps.py`, `admin.py`, `models.py`, `tests.py`, `views.py`,
`migrations/`. Same for the `startproject` files under `config/`. **Do not
restructure, rename, split, or remove default files**, even when they are
empty stubs. Add new modules (`urls.py`, `services.py`, `tasks.py`,
`forms.py`, `management/commands/...`) alongside the defaults.

If a refactor would require removing a default file, stop and ask first.

### The placeholder `app/` directory

There's an empty Django app at `<repo>/app/` that the user pre-created. It
is registered in `INSTALLED_APPS` but currently unused. **Leave it in
place** — same rule as above. The real apps for this project are `seasons/`,
`competitors/`, `results/`, `analytics/`, `web/`.

### No Makefile

The user prefers plain Python flows. Use the commands directly:

```bash
python -m black . && python -m isort .            # format
python -m black --check . && python -m isort --check-only .   # lint
python -m pytest                                  # tests
python manage.py migrate                          # db
python manage.py runserver                        # dev server
python manage.py sync_year 2025                   # ingest a season
python manage.py backfill_history --start 1950    # full history
```

Do not add a Makefile or `make`-style wrappers.

### Formatting

- Black: `line-length = 100`, `target-version = ["py312"]`
- isort: `profile = "black"`, `line_length = 100`
- Pre-commit runs both on commit; also trailing-whitespace, end-of-file-fixer,
  check-yaml, check-added-large-files.

Run `python -m black . && python -m isort .` after any non-trivial edit.

## Data rules (the load-bearing ones)

1. **jolpica points are truth.** Standings come from
   `/{year}/driverstandings` and `/{year}/constructorstandings` and are
   persisted as `Standing` rows snapshot-per-round. **Never recompute
   standings** in application code; read them from the DB.

2. **Team attribution lives on `Result.constructor`,** not a static
   driver→team map. Mid-season driver swaps would silently mis-attribute team
   stats otherwise.

3. **Idempotent ingest.** Every writer in `seasons/services/sync.py` uses
   `update_or_create` keyed on natural keys (`round`, `driver`, `session` for
   results; `round`, `driver` for qualifying; `round`, `kind`, `driver`,
   `constructor` for standings). Re-running any sync task on unchanged data
   must be a no-op.

4. **Rate limits (jolpica, unauthenticated):** 4 req/s burst, 500 req/hr
   sustained, no token. The client at `seasons/services/jolpica.py` enforces
   BOTH ceilings:
   - 0.3s inter-call spacer keeps the burst under 4 req/s.
   - A sliding-window throttle (`_RECENT_CALLS` deque + `_HOURLY_CAP = 480`)
     blocks before each request when 480 calls have been made in the last
     hour, leaving 20 req/hr of headroom.
   - On 429, the client honors `Retry-After` if present, otherwise falls back
     to exponential backoff (1, 2, 4, 8, 16, 32, 64 — up to 7 retries).
   Don't bypass any of this. Don't add concurrent fetches without revisiting
   the budget. `backfill_history` is resilient: a single round that fails
   logs and continues — it does not crash the whole task.

5. **FastF1 / telemetry is v2.** Top speed, raw laps, `SessionStat` — none of
   it lands until the v1 surface is solid. If the user asks for top-speed
   stats, point them at the v2 placeholder in `funstats.html` and confirm
   before pulling FastF1 in.

## Architecture in one breath

```
jolpica  ──►  Celery task (sync.py, idempotent update_or_create)
                  │
                  ▼
              Postgres  ──►  analytics/services.py (pure DB)
                                 │
                                 ▼
                             web/views.py (HTMX) ──►  templates/web/*.html
```

Cache invalidation is automatic via a version key:

```python
# end of sync task:
cache.set("f1:ver", now().isoformat())
# view side:
key = f"<feature>:<year>:{cache.get('f1:ver', '0')}"
```

Bump the version key whenever you mutate data outside the regular sync path,
or stale cached views will linger for 24h.

## Headline features

- `analytics.services.contenders(year, constructor=False)` — title eligibility
  math against the latest `Standing` snapshot, using remaining race + sprint
  points from the calendar. Constants live at the top of the module
  (`RACE_WIN=25`, `SPRINT_WIN=8`, constructors get the 1-2-finish caps).
- `analytics.services.most_improved(year, constructor=False)` — second-half
  avg minus first-half avg of points/round, computed from `Result` rows
  only — do not call jolpica's per-round standings endpoint 20× for this.

If either calculation needs to change (rule change, scoring system tweak),
update the constants and add a regression test in `analytics/tests.py`.

## Testing

`python -m pytest`. Existing coverage:

- `analytics/tests.py` — contenders boundary case + most-improved late-bloomer
- `seasons/tests.py` — jolpica pagination + 429 exponential backoff (uses
  `responses` library; no real network calls)

When adding analytics logic, add a fixture-driven test alongside it. When
adding sync logic, add a `responses`-mocked test that exercises the network
contract.

## What NOT to do

- Don't add DRF, Next.js, or any JS framework without explicit ask — v1 is
  HTMX + server-rendered templates.
- Don't introduce alternative data sources (FastF1, Sportradar, etc.)
  silently. v1 is jolpica-only.
- Don't recompute standings or championship points from `Result` rows when
  `Standing` already has the snapshot.
- Don't run concurrent jolpica fetches without revisiting the 500/hr ceiling.
- Don't reformat the whole repo in passing — the baseline is already
  black/isort-clean; only the lines you touched should change.
