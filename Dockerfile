# syntax=docker/dockerfile:1
# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Python dependency builder
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements/base.txt requirements/prod.txt ./requirements/
RUN pip install --upgrade pip \
 && pip install --no-cache-dir --prefix=/install -r requirements/prod.txt


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Runtime image
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
        mdbtools \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local
COPY . .

# Run collectstatic as root BEFORE switching to non-root user
RUN DJANGO_SETTINGS_MODULE=config.settings.base \
    DJANGO_SECRET_KEY=build-placeholder \
    python manage.py collectstatic --noinput

# Non-root user for security
RUN addgroup --system --gid 1001 traceboard \
 && adduser  --system --uid 1001 --ingroup traceboard --no-create-home traceboard \
 && chown -R traceboard:traceboard /app

USER traceboard

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

ENV DJANGO_SETTINGS_MODULE=config.settings.prod \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "2", \
     "--threads", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]