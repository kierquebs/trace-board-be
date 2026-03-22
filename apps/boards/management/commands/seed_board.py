"""
Management command: seed_board

Loads a local boardview file into the database and Redis cache for
local development/testing — no S3 or Celery required.

What it does:
  1. Reads the file from disk
  2. Detects format and parses it (runs the full parser pipeline)
  3. Creates a BoardFile DB record (or updates if same content_hash exists)
  4. Stores parsed JSON in Redis
  5. Saves raw bytes to local_board_storage/ (so the fallback read works)

Usage:
    python manage.py seed_board tests/fixtures/A2141_820-01700.brd
    python manage.py seed_board /path/to/board.brd --name "iPhone 15 Pro" --brand Apple
    python manage.py seed_board /path/to/board.brd --category laptop --status restricted
"""
import sys
from pathlib import Path

from django.core.cache import cache
from django.core.management.base import BaseCommand, CommandError

from apps.boards.models import BoardFile, BoardStatus
from apps.boards.parsers import parse_board_file
from apps.boards.parsers.detect import detect_format
from apps.boards.storage import upload_board_file


class Command(BaseCommand):
    help = "Load a local board file into the DB + Redis for local dev/testing."

    def add_arguments(self, parser):
        parser.add_argument(
            "filepath",
            help="Path to the boardview file (.brd, .bv, .fz, etc.)",
        )
        parser.add_argument(
            "--name",
            default="",
            help="Display name (default: filename without extension)",
        )
        parser.add_argument(
            "--brand",
            default="",
            help='Brand name e.g. "Apple", "Samsung"',
        )
        parser.add_argument(
            "--model",
            default="",
            dest="model_number",
            help='Model number e.g. "A2407", "820-01700"',
        )
        parser.add_argument(
            "--category",
            default="cellphone",
            choices=["cellphone", "laptop", "tablet", "desktop", "other"],
        )
        parser.add_argument(
            "--status",
            default="enabled",
            choices=["enabled", "disabled", "restricted"],
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-parse even if a board with this hash already exists",
        )

    def handle(self, *args, **options):
        filepath = Path(options["filepath"])

        if not filepath.exists():
            raise CommandError(f"File not found: {filepath}")

        self.stdout.write(f"Loading: {filepath}")

        # ── Read file ───────────────────────────────────────────────────────
        file_bytes = filepath.read_bytes()
        content_hash = BoardFile.compute_hash(file_bytes)
        display_name = options["name"] or filepath.stem

        self.stdout.write(f"  Size:   {len(file_bytes):,} bytes")
        self.stdout.write(f"  Hash:   {content_hash[:16]}...")

        # ── Duplicate check ─────────────────────────────────────────────────
        existing = BoardFile.objects.filter(content_hash=content_hash).first()
        if existing and not options["force"]:
            self.stdout.write(
                self.style.WARNING(
                    f"  Board already exists: '{existing.name}' (id={existing.pk})\n"
                    f"  Use --force to re-parse and update."
                )
            )
            self._print_access_info(existing)
            return

        # ── Detect format ───────────────────────────────────────────────────
        fmt = detect_format(file_bytes, filepath.name)
        self.stdout.write(f"  Format: {fmt.value}")

        # ── Parse ───────────────────────────────────────────────────────────
        self.stdout.write("  Parsing...")
        result = parse_board_file(file_bytes, filepath.name)

        if not result.success:
            raise CommandError(f"Parse failed: {result.error}")

        stats = result.board.stats
        self.stdout.write(
            f"  Parsed: {stats['part_count']} parts, "
            f"{stats['pin_count']} pins, "
            f"{stats['net_count']} nets"
        )

        # ── Save raw file to local storage ──────────────────────────────────
        s3_key = BoardFile.build_s3_key(content_hash, filepath.name)
        upload_board_file(s3_key, file_bytes)

        # ── Create or update DB record ──────────────────────────────────────
        if existing and options["force"]:
            board = existing
            board.name = display_name or board.name
        else:
            # Get the first admin user to assign as uploader
            from django.contrib.auth import get_user_model
            User = get_user_model()
            admin = User.objects.filter(role="admin").first()
            if not admin:
                raise CommandError(
                    "No admin user found. Create one first:\n"
                    "  python manage.py createsuperuser\n"
                    "  (then set role='admin' in Django admin or shell)"
                )

            board = BoardFile(
                uploaded_by=admin,
                original_filename=filepath.name,
                s3_key=s3_key,
                content_hash=content_hash,
                file_size=len(file_bytes),
            )

        board.name = display_name
        board.format = fmt.value
        board.brand = options["brand"]
        board.model_number = options["model_number"]
        board.category = options["category"]
        board.status = options["status"]
        board.parse_status = "success"
        board.parse_error = ""
        board.part_count = stats["part_count"]
        board.pin_count = stats["pin_count"]
        board.net_count = stats["net_count"]
        board.save()

        # ── Cache parsed JSON in Redis ──────────────────────────────────────
        board_json = result.board.to_json()
        cache.set(board.redis_cache_key, board_json, timeout=604800)  # 7 days

        self.stdout.write(
            self.style.SUCCESS(
                f"\n✅ Board seeded successfully!\n"
                f"   Name:   {board.name}\n"
                f"   ID:     {board.pk}\n"
                f"   Format: {board.format}\n"
                f"   Parts:  {board.part_count}\n"
                f"   Pins:   {board.pin_count}\n"
                f"   Nets:   {board.net_count}\n"
            )
        )
        self._print_access_info(board)

    def _print_access_info(self, board: BoardFile) -> None:
        self.stdout.write(
            self.style.HTTP_INFO(
                f"\nTest endpoints:\n"
                f"  Metadata: GET /api/boards/{board.pk}/\n"
                f"  Render:   GET /api/boards/{board.pk}/view/\n"
                f"            (requires Authorization: Bearer <token>)\n"
            )
        )
