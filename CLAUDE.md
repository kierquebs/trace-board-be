# TraceBoard — Claude Code Instructions

## Project Identity
- **Name:** TraceBoard
- **What it is:** Web-based PCB boardview file viewer SaaS for cellphone/laptop repair technicians (PH/SEA market)
- **Owner:** Kier — DevOps/software engineer, Philippines, co-runs Prime Biznest Management Corp
- **Backend repo:** https://github.com/kierquebs/trace-board-be.git
- **Business model:** Paid subscription — PayMongo (GCash/Maya/cards), Stripe fallback

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Django 5 + DRF 3.15, Python 3.12 |
| Auth | djangorestframework-simplejwt (JWT, 30min access / 7day refresh) |
| Task queue | Celery + Redis |
| Database | PostgreSQL 16 (RDS in prod, Docker in dev) |
| Cache | Redis (django-redis) |
| File storage | AWS S3 private bucket (`ap-southeast-1`) |
| Frontend | React 18 + TypeScript + Vite + Pixi.js (separate repo) |
| Infra | AWS ECS Fargate, CloudFront, Terraform (separate repo) |

---

## Critical Security Rules — Never Violate

1. **`s3_key` is never sent to any client** — not in any serializer, response, or log visible to users
2. **`content_hash` is never sent to technicians** — only admin serializers may include it
3. **Raw board file bytes never leave the server** — only parsed JSON is served via `/api/boards/{id}/view/`
4. **No presigned S3 URLs for board files** — ever
5. **Board view endpoint auth chain:** authenticated → not suspended → active subscription → board accessible (CanViewBoard) → parse_status == success

---

## App Structure

```
apps/
├── accounts/       User model (admin|technician), JWT login, permissions
├── boards/         BoardFile model, parsers, Celery parse task, S3 storage
├── annotations/    Per-user per-board notes/markers
├── billing/        Plan, Subscription, Payment, PayMongo webhooks
└── admin_panel/    Admin-only endpoints (board mgmt, user mgmt, analytics)
```

---

## User Roles

**Admin** — uploads/manages boards, manages technicians, sees all analytics. No subscription needed.

**Technician** — subscribes, views/searches/annotates boards. Cannot upload or access admin endpoints.

### Key Permission Classes (`apps/accounts/permissions.py`)
- `IsAdmin` — admin role + not suspended
- `IsTechnician` — technician role + not suspended
- `HasActiveSubscription` — active sub OR admin
- `CanViewBoard` — object-level: checks board status + tier match

---

## Database Models (key fields)

**`BoardFile`** — `s3_key`, `content_hash`, `parse_status` (pending/parsing/success/failed), `status` (enabled/disabled/restricted), `min_tier`, `redis_cache_key` property

**`User`** — `role` (admin|technician), `is_suspended`, `has_active_subscription` property, `subscription_tier` property

**`Subscription`** — `status` (active/trial/past_due/cancelled), `current_period_end`, `plan` FK

**`Plan`** — slugs: `starter` (₱299), `pro` (₱599), `shop` (₱1499)

> ⚠️ No Django migrations exist yet — run `python manage.py makemigrations` then `migrate` first time

---

## API Endpoints

```
POST /api/auth/register/              Technician self-register
POST /api/auth/login/                 Returns {access, refresh, user{role, has_active_subscription}}
POST /api/auth/refresh/
POST /api/auth/logout/                Blacklists refresh token
GET  /api/auth/me/                    Current user profile

GET  /api/boards/                     List enabled boards (technician) / all (admin)
GET  /api/boards/{id}/                Board metadata (no raw file data)
GET  /api/boards/{id}/view/           ★ Parsed board JSON for rendering
GET  /api/boards/{id}/annotations/    My annotations
POST /api/boards/{id}/annotations/

GET  /api/billing/plans/              Public plan list
POST /api/billing/subscribe/          Start PayMongo checkout
GET  /api/billing/status/             My subscription
POST /api/billing/cancel/
POST /api/billing/webhooks/paymongo/  PayMongo webhook (no auth)

GET  /api/admin/boards/               All boards incl. disabled
POST /api/admin/boards/upload/        Upload board file → triggers Celery parse
GET/PATCH/DELETE /api/admin/boards/{id}/
POST /api/admin/boards/{id}/reparse/
GET  /api/admin/users/
GET/PATCH /api/admin/users/{id}/
GET  /api/admin/analytics/overview/
GET  /api/admin/analytics/popular-boards/
```

---

## Board File Parsers (`apps/boards/parsers/`)

All parsers implement `parse(file_bytes: bytes, filename: str) -> ParseResult`.
Output is always `ParsedBoard` — unified model regardless of input format.

| File | Format | Status |
|---|---|---|
| `brd_landrex.py` | Landrex `.brd` (binary encoded) | ✅ Complete |
| `brd2.py` | TOPTEST `.brd` (plain text) | ✅ Complete |
| `bv.py` | `.bv` / `.bvr` | ❌ Not built |
| `fz.py` | `.fz` XOR-encrypted (Asus) | ❌ Not built |
| `asc.py` | `.asc` plain ASCII | ❌ Not built |

### Landrex decode formula
```python
decoded_ascii = chr(255 - ((byte & 0x3F) << 2) - ((byte >> 6) & 3))
```

### ParsedBoard → JSON structure (what frontend receives)
```json
{
  "format": "brd_landrex",
  "width": 13450.0,
  "height": 4813.0,
  "outline": [{"x": 0, "y": 0}, ...],
  "parts": [{"id": "U1", "name": "U1", "side": "top", "bounds": {...}}],
  "pins": [{"id": "U1_0", "part_id": "U1", "net_name": "GND", "position": {"x": 100, "y": 200}, "side": "top"}],
  "nets": [{"id": "1", "name": "GND", "pin_ids": [...], "is_ground": true, "is_power": false}],
  "nails": []
}
```

Coordinates are in **mils** (thousandths of an inch).

---

## Board Parse Flow (Upload → View)

```
Admin uploads file
  → AdminBoardUploadView validates + stores to S3
  → parse_board_task.delay(board.pk)  [Celery]
    → read_board_file(s3_key)         [S3, bytes never leave server]
    → parse_board_file(bytes, name)   [parser registry]
    → cache.set(redis_cache_key, board_json, ttl=7days)
    → board.mark_success(counts)

Technician requests /api/boards/{id}/view/
  → Auth chain (5 checks)
  → cache.get(redis_cache_key)  → hit: return JSON immediately
  → miss: re-read S3 → re-parse → re-cache → return JSON
```

---

## Storage (`apps/boards/storage.py`)

Dev mode (`USE_S3=False`, when `AWS_STORAGE_BUCKET_NAME` is blank):
- Files saved to `local_board_storage/` directory
- Enables full upload/parse/view flow without AWS

Prod mode (`USE_S3=True`):
- Private S3 bucket, `ap-southeast-1`
- `ServerSideEncryption: AES256`

---

## Dev Setup

```bash
cp .env.example .env          # fill in AWS creds + bucket name
docker compose build
docker compose up -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
# Set role=admin in shell: User.objects.filter(username='x').update(role='admin')
docker compose exec web python manage.py seed_plans
docker compose exec web python manage.py seed_board tests/fixtures/A2141_820-01700.brd \
  --name "MacBook Pro 16 2019" --brand Apple --model 820-01700 --category laptop
docker compose exec web pytest
```

### Key ports
- `8000` — Django API
- `5433` — PostgreSQL (mapped from 5432 inside container)
- `6371` — Redis (mapped from 6379)
- `5555` — Flower (Celery monitor, `--profile monitoring`)

---

## Coding Standards

**Python / Django**
- Python 3.12+, type hints on all function signatures
- Class-based DRF views (`APIView`)
- Custom permission classes — never use `request.user.role == 'admin'` inline
- `ruff` for linting
- `pytest` + `factory_boy` for tests (fixtures in `tests/conftest.py`)
- API envelope: always `{"data": ...}` for success, `{"error": "..."}` for failure

**General**
- Conventional commits: `feat:`, `fix:`, `refactor:`, `test:`, `chore:`
- Never hardcode AWS credentials — always from `os.environ`
- Board parse errors → `board.mark_failed(error)`, never raise to client

---

## Environment Variables (`.env`)

```
DJANGO_SETTINGS_MODULE=config.settings.dev
DJANGO_SECRET_KEY=
POSTGRES_DB=traceboard
POSTGRES_USER=traceboard
POSTGRES_PASSWORD=traceboard
POSTGRES_HOST=db
POSTGRES_PORT=5432
REDIS_URL=redis://redis:6379/0
AWS_REGION=ap-southeast-1
AWS_STORAGE_BUCKET_NAME=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
PAYMONGO_SECRET_KEY=sk_test_
PAYMONGO_PUBLIC_KEY=pk_test_
PAYMONGO_WEBHOOK_SECRET=
FRONTEND_URL=http://localhost:5173
```

---

## Current Status

### ✅ Done
- `apps/accounts` — User model, custom JWT login (returns role + subscription in response + token claims), register, logout, permissions
- `apps/accounts/views.py` — Password reset: `POST /api/auth/password/reset/` + `POST /api/auth/password/reset/confirm/` (Django token generator, frontend-linked email)
- `apps/boards/parsers/brd_landrex.py` — Landrex binary format, fully reverse-engineered, 27/27 tests passing (7512 parts, 25497 pins, 4186 nets on 820-01700)
- `apps/boards/parsers/brd2.py` — TOPTEST plain-text format
- `apps/boards/views.py` — Board list, detail, view endpoint (full auth chain + Redis cache)
- `apps/boards/storage.py` — S3 + local dev fallback
- `apps/admin_panel/views.py` — All admin endpoints (board upload, user mgmt, analytics)
- `apps/billing/models.py` — Plan, Subscription, Payment models
- `apps/billing/paymongo.py` — PayMongo Checkout Session API client (Basic auth, user/plan metadata for webhook correlation)
- `apps/billing/views.py` — Real PayMongo checkout (`_create_paymongo_checkout`, 502 on error) + subscription activation on `payment.paid` webhook (`_handle_payment_paid` upserts Subscription + Payment)
- `apps/boards/management/commands/seed_board.py` — Load local .brd file for dev
- `apps/billing/management/commands/seed_plans.py` — Seed Starter/Pro/Shop plans
- `tests/` — conftest with factories, board view tests (22 cases), parser tests (13 cases), billing tests (15 cases)

### 🔴 Next Priority
- `apps/boards/parsers/bv.py` — BV/BVR format parser (P1 priority)
- Annotation endpoints (models exist, views stubbed)
- `apps/billing/` — Plan seed data migration

### 🟡 After That
- `apps/boards/parsers/fz.py` — FZ XOR-encrypted (Asus) format
- `apps/boards/parsers/asc.py` — ASC plain ASCII format

---

## Domain Terms

| Term | Meaning |
|---|---|
| Board / Boardview | PCB layout file (.brd, .bv, .fz, etc.) |
| Part / Component | Physical component on PCB (U1, C45, R100) |
| Pin / Terminal | Connection point on a component — clicking triggers net trace |
| Net | Named electrical connection linking multiple pins (GND, PPBUS_G3H) |
| Net trace | Visual display of connection lines + halos when a pin is clicked |
| Nail / Test point | Probe-accessible point linked to a net |
| Side | Top or bottom PCB layer |
| Halo | Pulsing semi-transparent circle drawn around pins during net tracing |
| Board status | `enabled` / `disabled` / `restricted` — admin-controlled |
| PP* rails | Apple power-positive nets (PPBUS, PPVCC, PPDCIN) — always `is_power=True` |
