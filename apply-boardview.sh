#!/bin/bash
set -e
TARBALL="nailtrace-boardview.tar.gz"
[ -f "$TARBALL" ] || { echo "ERROR: $TARBALL not found"; exit 1; }
tar -xzf "$TARBALL"
git add \
  apps/boards/storage.py \
  apps/boards/management/ \
  apps/billing/management/ \
  tests/test_boards/test_board_views.py
git commit -m "feat: board view endpoint wiring + local dev storage

apps/boards/storage.py:
- Local filesystem fallback when USE_S3=False (no AWS needed in dev)
- Files saved to local_board_storage/ directory
- Respects USE_S3 flag from dev.py settings

apps/boards/management/commands/seed_board.py:
- Loads a .brd file from disk, parses it, seeds DB + Redis
- No S3 or Celery required for local testing
- Usage: python manage.py seed_board tests/fixtures/A2141_820-01700.brd

apps/billing/management/commands/seed_plans.py:
- Creates Starter/Pro/Shop plans in DB (idempotent)
- Usage: python manage.py seed_plans

tests/test_boards/test_board_views.py:
- 22 test cases covering auth gates, subscription gates, board status,
  response shape, security (s3_key/hash never leaked), cache behavior,
  tier restrictions"
git push origin main
echo "Done!"
