"""
Celery tasks for board file processing.

parse_board_task is triggered immediately after admin upload.
It reads the raw file from S3, parses it, caches the JSON in Redis,
and updates the BoardFile's parse_status + metadata.

The raw file bytes never leave the server.
"""
import logging

from celery import shared_task
from django.core.cache import cache

from .models import BoardFile
from .parsers import parse_board_file
from .storage import read_board_file

logger = logging.getLogger(__name__)


@shared_task(
    bind=True,
    max_retries=3,
    default_retry_delay=30,
    name="boards.parse_board",
)
def parse_board_task(self, board_id: int) -> dict:
    """
    Parse a board file and cache the result.

    Steps:
      1. Load BoardFile from DB
      2. Mark as 'parsing'
      3. Read raw bytes from S3
      4. Run parser → ParsedBoard
      5. Serialize to JSON
      6. Store JSON in Redis (TTL = 7 days)
      7. Update BoardFile with parse metadata (counts, format, status)

    On failure: mark board as failed, log error, retry up to 3 times.
    """
    try:
        board = BoardFile.objects.get(pk=board_id)
    except BoardFile.DoesNotExist:
        logger.error("parse_board_task: BoardFile %d not found", board_id)
        return {"status": "error", "error": "Board not found"}

    logger.info("Parsing board %d (%s)", board_id, board.original_filename)
    board.mark_parsing()

    try:
        # Step 1: Read raw bytes from S3 (never sent to client)
        file_bytes = read_board_file(board.s3_key)

        # Step 2: Parse
        result = parse_board_file(file_bytes, board.original_filename)

        if not result.success:
            board.mark_failed(result.error)
            logger.error("Parse failed for board %d: %s", board_id, result.error)
            return {"status": "failed", "error": result.error}

        # Step 3: Cache JSON in Redis
        board_json = result.board.to_json()
        cache.set(board.redis_cache_key, board_json, timeout=604800)  # 7 days

        # Step 4: Update DB metadata
        stats = result.board.stats
        board.mark_success(
            part_count=stats["part_count"],
            pin_count=stats["pin_count"],
            net_count=stats["net_count"],
            fmt=stats["format"],
        )

        logger.info(
            "Board %d parsed successfully: %d parts, %d pins, %d nets",
            board_id,
            stats["part_count"],
            stats["pin_count"],
            stats["net_count"],
        )
        return {"status": "success", **stats}

    except Exception as exc:
        logger.exception("Unexpected error parsing board %d", board_id)
        board.mark_failed(str(exc))

        # Retry with exponential backoff
        raise self.retry(exc=exc, countdown=30 * (2 ** self.request.retries))


@shared_task(name="boards.invalidate_cache")
def invalidate_board_cache(content_hash: str) -> None:
    """Remove a board's parsed JSON from Redis. Called after board re-parse."""
    key = f"board:parsed:{content_hash}"
    cache.delete(key)
    logger.info("Invalidated cache for board hash %s", content_hash[:8])
