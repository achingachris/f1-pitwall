"""
Django settings for config project.
"""

import os
from pathlib import Path

from decouple import Csv, config

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config("DJANGO_SECRET_KEY", default="dev-insecure-key-change-me")
DEBUG = config("DJANGO_DEBUG", default=True, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# Behind nginx (or similar) in production — fixes admin login CSRF 403 on HTTPS.
_csrf_trusted = config("DJANGO_CSRF_TRUSTED_ORIGINS", default="", cast=Csv())
if _csrf_trusted:
    CSRF_TRUSTED_ORIGINS = _csrf_trusted
elif not DEBUG:
    CSRF_TRUSTED_ORIGINS = [
        f"https://{host}"
        for host in ALLOWED_HOSTS
        if host not in ("localhost", "127.0.0.1")
    ]
if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_htmx",
    "app.apps.AppConfig",
    "seasons.apps.SeasonsConfig",
    "competitors.apps.CompetitorsConfig",
    "results.apps.ResultsConfig",
    "analytics.apps.AnalyticsConfig",
    "web.apps.WebConfig",
    "bot.apps.BotConfig",
    "telemetry.apps.TelemetryConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django_htmx.middleware.HtmxMiddleware",
    "web.middleware.RequestLogMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

if config("POSTGRES_HOST", default=""):
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": config("POSTGRES_DB", default="f1"),
            "USER": config("POSTGRES_USER", default="f1"),
            "PASSWORD": config("POSTGRES_PASSWORD", default="f1"),
            "HOST": config("POSTGRES_HOST"),
            "PORT": config("POSTGRES_PORT", default="5432"),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "static_collected"
STATICFILES_DIRS = [BASE_DIR / "web" / "static"] if (BASE_DIR / "web" / "static").exists() else []
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Redis-backed cache (falls back to local memory if no REDIS_URL).
REDIS_URL = config("REDIS_URL", default="")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": REDIS_URL,
        }
    }
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# Celery.
CELERY_BROKER_URL = config("CELERY_BROKER_URL", default=REDIS_URL or "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = config(
    "CELERY_RESULT_BACKEND", default=REDIS_URL or "redis://localhost:6379/1"
)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_TASK_TIME_LIMIT = 60 * 60  # 1h hard cap for backfill chunks

# jolpica client.
JOLPICA_BASE = config("JOLPICA_BASE", default="https://api.jolpi.ca/ergast/f1")
JOLPICA_USER_AGENT = config("JOLPICA_USER_AGENT", default="f1app/1.0")

# FastF1 (v2 telemetry). Directory must be writable by web/worker/bot.
# Falls back to a repo-local .fastf1cache/ dir when no env var is set so dev
# environments without docker still work.
FASTF1_CACHE_DIR = config("FASTF1_CACHE_DIR", default=str(BASE_DIR / ".fastf1cache"))

# Telegram bot.
TELEGRAM_BOT_TOKEN = config("TELEGRAM_BOT_TOKEN", default="")
TELEGRAM_WEBHOOK_SECRET = config("TELEGRAM_WEBHOOK_SECRET", default="")
TELEGRAM_ADMIN_IDS = config("TELEGRAM_ADMIN_IDS", default="", cast=Csv(int))

# Logging.
#
# Two rotating files in production: `web.log` (request middleware + Django's
# `django.request` 4xx/5xx records) and `bot.log` (Telegram command/callback
# events). Dev (DEBUG=True) logs to stdout only — file handlers are skipped to
# keep the working tree clean. Stdout stays on in prod too so `docker logs`
# remains useful.
LOG_DIR = config("LOG_DIR", default=str(BASE_DIR / "logs"))
if not DEBUG:
    os.makedirs(LOG_DIR, exist_ok=True)

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s — %(message)s"
_FILE_HANDLERS = (
    {}
    if DEBUG
    else {
        "web_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "web.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "default",
        },
        "bot_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": os.path.join(LOG_DIR, "bot.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "formatter": "default",
        },
    }
)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"default": {"format": _LOG_FORMAT}},
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "default"},
        **_FILE_HANDLERS,
    },
    "loggers": {
        "web.request": {
            "handlers": ["console"] if DEBUG else ["console", "web_file"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"] if DEBUG else ["console", "web_file"],
            "level": "WARNING",
            "propagate": False,
        },
        "bot": {
            "handlers": ["console"] if DEBUG else ["console", "bot_file"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
