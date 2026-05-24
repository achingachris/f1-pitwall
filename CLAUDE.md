# CLAUDE.md

Project-specific guidance for Claude Code sessions in this repo.

## What this is

**Pitwall** — Django 5 + HTMX monolith for F1 stats. jolpica is the primary
data source; FastF1 is layered on top as v2 telemetry (additive only — see
"FastF1 / telemetry" below). Deployed via docker-compose (`web`, `worker`,
`beat`, `bot`, `postgres`, `redis`) behind Nginx + Certbot, same flow as the
user's other apps.

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

5. **FastF1 / telemetry (v2) is additive only.** Lives in the `telemetry/`
   app. Four tables, all written by a single entry point
   `telemetry.services.sync.sync_session(round, kind)` off one FastF1 load:
   - `Session` keyed on `(round, kind)`,
   - `SessionStat` keyed on `(session, driver)` — fastest lap, top speed,
     sector bests,
   - `Lap` keyed on `(session, driver, number)` — per-lap times, sectors,
     compound, tyre life, stint, position, speed trap, PB/deleted flags,
   - `Stint` keyed on `(session, driver, number)` — compound, lap range,
     count, age-at-start.
   `Lap` and `Stint` are upserted via `bulk_create(update_conflicts=True)`;
   the natural-key `UniqueConstraint`s are load-bearing.
   **jolpica stays truth for `Result` and `Standing` — telemetry never
   overwrites them.**
   - Coverage starts in **2018** (`FASTF1_MIN_YEAR`). Pre-2018 seasons stay
     jolpica-only; the client raises `FastF1Unavailable` (or
     `sync_session_safe` swallows it).
   - Cache: FastF1's on-disk Parquet cache lives at `settings.FASTF1_CACHE_DIR`
     (`/cache/fastf1` under docker, `./.fastf1cache` locally). Mounted as a
     named volume on `web`, `worker`, and `bot`.
   - Sync surface: `python manage.py sync_session <year> <round> <kind>` and
     `telemetry.tasks.sync_session_task`. Triggered manually — no Beat entry
     yet. **Run `sync_year` first** so the Driver/Constructor rows exist;
     telemetry looks up drivers by their 3-letter `code` and skips unknown
     ones rather than inventing rows.
   - Telemetry syncs must prune stale `SessionStat`, `Lap`, and `Stint` rows
     when a corrected FastF1 response no longer contains them.
   - `fastf1` is imported **lazily** inside the client wrapper so the rest of
     the app (tests, jolpica sync, the bot) doesn't pull pandas/numpy on
     import. Keep it that way.

## Architecture in one breath

```
jolpica  ──►  seasons/services/sync.py (idempotent update_or_create)
                  │
FastF1  ──►  telemetry/services/sync.py (idempotent update_or_create)
                  │
                  ▼
              Postgres  ──►  analytics/services.py (pure DB, jolpica tables)
                          ──►  telemetry/services/queries.py (pure DB, telemetry tables)
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

## Telegram bot (`bot/` app)

A Telegram bot exposes the same features as the web app. Implementation lives
under `bot/`, library is `pyTelegramBotAPI` (sync — pairs naturally with the
sync Django ORM, no `sync_to_async` ceremony).

- **Two transports, same handlers.**
  - **Polling (dev):** `python manage.py run_telegram_bot` blocks the process
    and long-polls. The `bot` docker-compose service runs this. If
    `TELEGRAM_BOT_TOKEN` is unset the worker exits cleanly so dev environments
    without a token aren't broken.
  - **Auto-start with runserver:** `bot/apps.py::BotConfig.ready()` also
    spawns the poller in a daemon thread when `runserver` boots, gated on
    `TELEGRAM_BOT_TOKEN` being set, the auto-reloader's child process (`RUN_MAIN`)
    to avoid duplicate pollers, and `RUN_BOT_WITH_SERVER` not being `"false"`.
    Set `RUN_BOT_WITH_SERVER=false` in `.env` to opt out (useful when running
    `runserver` while a separate bot worker is already polling).
  - **Webhook (prod):** `bot.views.telegram_webhook` mounted at
    `/telegram/webhook/<secret>/`. The `secret` path segment is
    constant-time-compared against `TELEGRAM_WEBHOOK_SECRET`; mismatch → 404
    (don't leak existence). View is `@csrf_exempt` and catches all exceptions
    so a bad payload never causes a 5xx (Telegram retries on non-2xx).
- **Reuse.** `bot/formatters.py` calls the existing `analytics.services.*`,
  `web.nationalities.flag_emoji`, `web.services.wiki.fetch_summary`, and the
  ORM directly. **Do not duplicate analytics logic in the bot layer.**
- **Secrets.** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, and
  `TELEGRAM_ADMIN_IDS` live in `.env` only — never commit, never log.
- **Wordmark.** All bot output is prefixed with `🏎️ Pitwall` so users recognise
  the bot's identity. Keep this consistent if adding new handlers.

## Logging

In production (`DJANGO_DEBUG=False`), two rotating log files are written by
the stdlib `RotatingFileHandler`:

- `<LOG_DIR>/web.log` — `web.request` (one line per HTTP request from
  `web.middleware.RequestLogMiddleware`) + `django.request` (4xx/5xx).
- `<LOG_DIR>/bot.log` — `bot.event` (one line per Telegram command / callback,
  including user id, username, chat id, command label, raw text/data).

`LOG_DIR` defaults to `./logs/` locally and is set to `/var/log/pitwall` in
`docker-compose.yml` (mounted as the `logs` named volume). Stdout handlers
stay attached in prod so `docker logs` keeps working. Dev (`DEBUG=True`)
skips the file handlers entirely.

When adding new handlers to the bot, call `_log_message(message, label)` (or
`_log_callback(call, label)`) at the top — otherwise the new command won't
appear in the audit trail. Don't log secrets or full message bodies; the
helpers truncate to 200 chars by design.

## What NOT to do

- Don't add DRF, Next.js, or any JS framework without explicit ask — the UI
  is HTMX + server-rendered templates.
- Don't introduce additional data sources (Sportradar, etc.) silently.
  jolpica + FastF1 are the only two allowed; new sources need an explicit
  ask.
- Don't recompute standings or championship points from `Result` rows when
  `Standing` already has the snapshot.
- Don't let telemetry write into `Result`, `Standing`, `Qualifying`, or any
  jolpica table — those stay truth.
- Don't run concurrent jolpica fetches without revisiting the 500/hr ceiling.
- Don't import `fastf1` at module top level outside `telemetry/services/`.
  Pandas/numpy must not load just because someone imported the bot or ran a
  jolpica command.
- Don't reformat the whole repo in passing — the baseline is already
  black/isort-clean; only the lines you touched should change.
