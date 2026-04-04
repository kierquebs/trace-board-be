"""
Production settings — AWS RDS + ElastiCache.
All secrets come from environment variables / AWS Secrets Manager.
"""
from .base import *  # noqa: F401, F403
import sentry_sdk
from sentry_sdk.integrations.django import DjangoIntegration
from sentry_sdk.integrations.celery import CeleryIntegration

DEBUG = False

ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")

# ---------------------------------------------------------------------------
# Database — AWS RDS PostgreSQL
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["POSTGRES_DB"],
        "USER": os.environ["POSTGRES_USER"],
        "PASSWORD": os.environ["POSTGRES_PASSWORD"],
        "HOST": os.environ["POSTGRES_HOST"],
        "PORT": os.environ.get("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {"sslmode": "require"},
    }
}

# ---------------------------------------------------------------------------
# Redis — AWS ElastiCache
# ---------------------------------------------------------------------------
REDIS_URL = os.environ["REDIS_URL"]
REDIS_SSL_CERT_REQS = os.environ.get("REDIS_SSL_CERT_REQS", None)

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "CONNECTION_POOL_KWARGS": {
                "max_connections": 50,
                "ssl_cert_reqs": REDIS_SSL_CERT_REQS
                },
        },
    }
}

CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL")
if CELERY_BROKER_URL and CELERY_BROKER_URL.startswith("rediss://"):
    # Append the required SSL certificate requirement parameter
    if "ssl_cert_reqs" not in CELERY_BROKER_URL:
        separator = "&" if "?" in CELERY_BROKER_URL else "?"
        CELERY_BROKER_URL += f"{separator}ssl_cert_reqs=none" # Use 'required' for production with CA certs

CELERY_RESULT_BACKEND = CELERY_BROKER_URL

# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
SECURE_SSL_REDIRECT = False  # Handled by ALB
SECURE_HSTS_SECONDS = 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False  # ALB terminates SSL, so cookies are set as secure=False but we still enforce HTTPS in views and middleware

CSRF_TRUSTED_ORIGINS = [
    "http://trace-board-dev-alb-138337456.ap-southeast-1.elb.amazonaws.com",
]

# ---------------------------------------------------------------------------
# CORS — only the production frontend
# ---------------------------------------------------------------------------
CORS_ALLOWED_ORIGINS = os.environ.get("CORS_ALLOWED_ORIGINS", "").split(",")
CORS_ALLOW_CREDENTIALS = True

# ---------------------------------------------------------------------------
# Sentry
# ---------------------------------------------------------------------------
SENTRY_DSN = os.environ.get("SENTRY_DSN", "")
if SENTRY_DSN:
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        traces_sample_rate=0.2,
        send_default_pii=False,
    )

# ---------------------------------------------------------------------------
# Email — SES
# ---------------------------------------------------------------------------
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "email-smtp.ap-southeast-1.amazonaws.com")
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@nailtrace.app")
