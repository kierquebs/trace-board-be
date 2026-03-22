"""
Development settings — uses local Postgres + Redis via docker-compose.
"""
from .base import *  # noqa: F401, F403

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "0.0.0.0"]

# ---------------------------------------------------------------------------
# Database — local Postgres (docker-compose)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("POSTGRES_DB", "nailtrace"),
        "USER": os.environ.get("POSTGRES_USER", "nailtrace"),
        "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "nailtrace"),
        "HOST": os.environ.get("POSTGRES_HOST", "db"),
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
    }
}

# ---------------------------------------------------------------------------
# Redis — local (docker-compose)
# ---------------------------------------------------------------------------
REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_KWARGS": {"max_connections": 20},
        },
    }
}

CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

# ---------------------------------------------------------------------------
# CORS — allow Vite dev server
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# S3 — use local MinIO or skip if no bucket configured
# ---------------------------------------------------------------------------
USE_S3 = bool(os.environ.get("AWS_STORAGE_BUCKET_NAME"))

# ---------------------------------------------------------------------------
# Email — console backend for dev
# ---------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Debug toolbar
INSTALLED_APPS += ["debug_toolbar"]  # noqa: F405
MIDDLEWARE = ["debug_toolbar.middleware.DebugToolbarMiddleware"] + MIDDLEWARE  # noqa: F405
INTERNAL_IPS = ["127.0.0.1"]
