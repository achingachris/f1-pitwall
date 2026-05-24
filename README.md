# Pitwall — F1 stats

A Django + HTMX app for Formula 1 season analysis. Race results and standings
come from [jolpica-f1](https://github.com/jolpica/jolpica-f1) (the Ergast
successor); lap-level telemetry comes from [FastF1](https://docs.fastf1.dev/)
for 2018+ seasons. Both are cached in Postgres; the public site never hits
either source directly.

## Features

- **Race weekend tracker** — landing page surfaces the current race weekend or
  next upcoming race with a live countdown to the next session.
- **Per-GP analysis** — race + sprint + qualifying for any round.
- **Title contenders** — drivers (and constructors) who can still
  mathematically win the championship, given remaining race and sprint points.
- **Most improved** — second-half vs first-half points-per-round delta.
- **Standings** — driver and constructor tables, snapshot per round.
- **Fun stats** — season-fastest lap, fastest lap per GP, slowest classified
  finisher.
- **Top speeds** *(FastF1)* — best speed-trap reading per driver across a
  season.
- **Lap by lap** *(FastF1)* — per-driver stint summary (compound, lap count)
  and full lap-by-lap detail for any 2018+ race.
- **Nationality flags** — every driver and team row carries its flag.
- **Telegram bot** — every web feature also available as a `/command` in chat.

## Stack

Django 5.2 · HTMX · vanilla CSS (light/dark theme) · Postgres 16 · Redis ·
Celery · FastF1 · pyTelegramBotAPI · Black + isort · pytest · Docker Compose.

## Quickstart (local)

```bash
python3 -m venv .venv
source .venv/bin/activate.fish          # or activate / activate.bash
pip install -r requirements.txt
cp .env.example .env                    # leave POSTGRES_HOST empty to use sqlite

python manage.py migrate
python manage.py runserver
```

All sync commands (`sync_year`, `backfill_history`, `sync_session`) enqueue
to Celery — they do not execute in-process. For local dev that means you
also need Redis + a worker:

```bash
docker compose up -d redis              # or run redis-server locally
celery -A config worker -l info --concurrency 1     # in a second terminal

python manage.py sync_year 2025         # queues; check the worker terminal for progress
```

Open <http://localhost:8000>.

Optional — pull FastF1 race-lap data for a specific race (requires the year
to be jolpica-synced first; 2018+ only):

```bash
python manage.py sync_session 2025 1 race
```

For a full historical backfill (~10–15 minutes at the rate-safe pace).
`--reverse` syncs the current season first and walks back to 1950, so the
public site gets useful data immediately while older years stream in:

```bash
python manage.py backfill_history --reverse
```

## Docker (prod-like)

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py sync_year $(date +%Y)
```

Services: `web` (gunicorn), `worker` (Celery), `beat` (scheduler), `bot`
(Telegram poller), `postgres`, `redis`. Beat schedules (all EAT):

- `sync_current_season` daily at 03:30 — incremental baseline.
- `sync_current_season` hourly on Sat + Sun — race-weekend catcher so
  results land within ~1h of the chequered flag.

The full historical backfill is a one-shot, run once per environment after
the first deploy (see *Quickstart*). A named volume `fastf1cache` is
mounted on `web`, `worker`, and `bot` so the multi-MB FastF1 Parquet cache
persists across container rebuilds.

## Telegram bot

Set `TELEGRAM_BOT_TOKEN` in `.env` (and `TELEGRAM_WEBHOOK_SECRET` for prod
webhook mode). The bot offers the same features as the web app:

```
/contenders /standings /season /round /driver /team
/improved   /funstats   /topspeeds /laps
```

Polling mode auto-starts with `runserver`; toggle with
`RUN_BOT_WITH_SERVER=false` if you'd rather run the dedicated `bot`
docker-compose worker instead. To refresh the `/` autocomplete menu after
adding new handlers:

```bash
python manage.py set_telegram_commands
```

## Dev commands

```bash
python -m black .                       # format
python -m isort .                       # sort imports
python -m black --check . && python -m isort --check-only .   # lint
python -m pytest                        # run tests
python manage.py check                  # Django system check
python manage.py shell                  # interactive shell
```

Pre-commit hooks (Black, isort, basic hygiene) install once:

```bash
pre-commit install
```

## Project layout

```
config/        # default startproject — settings, urls, wsgi, asgi, celery
seasons/       # Season, Circuit, Round + jolpica client + sync tasks + calendar
competitors/   # Driver, Constructor
results/       # Result (race + sprint), Qualifying, Standing
analytics/     # pure-DB services: contenders, most_improved, funstats
telemetry/     # FastF1 layer — Session, SessionStat, Lap, Stint + sync + queries
bot/           # Telegram bot — handlers, formatters, webhook + polling transports
web/           # HTMX views, templates, URL map, nationality flag filter
app/           # legacy placeholder app (intentionally left in place)
```

Default `startproject`/`startapp` scaffolding (`apps.py`, `admin.py`,
`tests.py`, `migrations/`) is preserved across every app — don't delete or
restructure it.

## Data rules

- **jolpica points are truth.** Standings are stored as a snapshot per round
  (`Standing` rows). Never recompute them client-side.
- **Team attribution lives on `Result.constructor`,** not a static driver→team
  map, so mid-season swaps work correctly.
- **Idempotent ingest.** Every writer in `seasons/services/sync.py` and
  `telemetry/services/sync.py` is keyed on natural keys
  (`update_or_create` for jolpica tables, `bulk_create(update_conflicts=True)`
  for `Lap`/`Stint`). Re-running a sync is a no-op.
- **Rate limits.** jolpica (unauthenticated) is 4 req/s burst, 500 req/hr
  sustained. The client in `seasons/services/jolpica.py` spaces calls at 0.3s
  and exponentially backs off on 429.
- **FastF1 is additive only.** Telemetry tables (`Session`, `SessionStat`,
  `Lap`, `Stint`) never write into the jolpica tables. Coverage starts in
  2018 (`FASTF1_MIN_YEAR`); the client raises `FastF1Unavailable` for older
  seasons. `fastf1` is imported lazily inside `telemetry/services/` so
  pandas/numpy don't load for code paths that don't need it.

## Logging

When `DJANGO_DEBUG=False` (i.e. production), Pitwall writes two rotating log
files via Python's `RotatingFileHandler` (10 MB × 5 backups each):

- `web.log` — one line per HTTP request from `web.middleware.RequestLogMiddleware`
  (`METHOD PATH STATUS DURATION_MS ip=… ua=…`), plus Django's `django.request`
  warnings/errors for 4xx/5xx.
- `bot.log` — one line per Telegram command or callback received (user id,
  username, chat id, command label, raw text/data — truncated to 200 chars).

`LOG_DIR` defaults to `./logs/` locally and is set to `/var/log/pitwall` under
docker-compose (mounted as a named `logs` volume so files survive container
rebuilds). Both loggers also tee to stdout so `docker logs <service>` keeps
working.

In dev (`DJANGO_DEBUG=True`) only stdout is used — no file handlers are
configured, no `logs/` dir gets created.

## Caching

Reads are cached on a version key bumped at the end of each successful sync,
so the public site only recomputes once per day:

```python
# at end of sync task:
cache.set("f1:ver", now().isoformat())
# in views:
key = f"contenders:driver:{year}:{cache.get('f1:ver', '0')}"
```

The landing-page race weekend tracker is intentionally **not** cached so
countdowns stay fresh.

## License

MIT.
