# Greedy Boole — F1 stats

A Django + HTMX app for Formula 1 season analysis. Data is sourced from
[jolpica-f1](https://github.com/jolpica/jolpica-f1) (the Ergast successor) and
cached in Postgres; the public site never hits jolpica directly.

## Features

- **Per-GP analysis** — race + sprint + qualifying for any round.
- **Title contenders** — drivers (and constructors) who can still mathematically
  win the championship, given remaining race and sprint points.
- **Most improved** — second-half vs first-half points-per-round delta.
- **Standings** — driver and constructor tables, snapshot per round.
- **Fun stats** — season-fastest lap, fastest lap per GP, slowest classified finisher.

FastF1 telemetry (top speed, raw laps) is deferred to v2.

## Stack

Django 5.2 · HTMX · Tailwind (CDN) · Chart.js · Postgres 16 · Redis · Celery ·
Black + isort · pytest · Docker Compose.

## Quickstart (local)

```bash
python3 -m venv .venv
source .venv/bin/activate.fish          # or activate / activate.bash
pip install -r requirements.txt
cp .env.example .env                    # leave POSTGRES_HOST empty to use sqlite

python manage.py migrate
python manage.py sync_year 2025         # pulls one season from jolpica
python manage.py runserver
```

Open <http://localhost:8000>.

For a full historical backfill (~10–15 minutes at the rate-safe pace):

```bash
python manage.py backfill_history --start 1950
```

## Docker (prod-like)

```bash
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py sync_year $(date +%Y)
```

Services: `web` (gunicorn), `worker` (Celery), `beat` (scheduler),
`postgres`, `redis`. Beat runs `sync_current_season` daily at 03:30 EAT.

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
seasons/       # Season, Circuit, Round + jolpica client + sync tasks
competitors/   # Driver, Constructor
results/       # Result (race + sprint), Qualifying, Standing
analytics/     # pure-DB services: contenders, most_improved, funstats
web/           # HTMX views, templates, URL map
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
- **Idempotent ingest.** Every writer in `seasons/services/sync.py` uses
  `update_or_create` keyed on natural keys (`round`, `driver`, `session`).
  Re-running a sync is a no-op.
- **Rate limits.** jolpica (unauthenticated) is 4 req/s burst, 500 req/hr
  sustained. The client in `seasons/services/jolpica.py` spaces calls at 0.3s
  and exponentially backs off on 429.

## Caching

Reads are cached on a version key bumped at the end of each successful sync,
so the public site only recomputes once per day:

```python
# at end of sync task:
cache.set("f1:ver", now().isoformat())
# in views:
key = f"contenders:driver:{year}:{cache.get('f1:ver', '0')}"
```

## License

MIT.
