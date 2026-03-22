"""
S3 operations for board files.

All board files live in a PRIVATE S3 bucket.
This module is the ONLY place that touches S3 keys directly.
No other module — and absolutely no API view — should generate presigned URLs
or expose s3_key values outside of this file.

LOCAL DEV MODE
--------------
When AWS_STORAGE_BUCKET_NAME is not set (i.e. USE_S3 = False in dev settings),
files are stored on the local filesystem under BASE_DIR/local_board_storage/.
This lets you develop and test the full upload → parse → view flow without AWS.
Set USE_S3=False (default when bucket not configured) to use local storage.
"""
import logging
from pathlib import Path
from typing import Optional

from django.conf import settings

logger = logging.getLogger(__name__)

# ── S3 client (lazy singleton) ─────────────────────────────────────────────

_s3_client = None


def _get_s3():
    """Lazy singleton S3 client."""
    global _s3_client
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client("s3", region_name=settings.AWS_REGION)
    return _s3_client


def _use_s3() -> bool:
    """True when S3 is configured (bucket name present)."""
    return bool(getattr(settings, "USE_S3", False))


def _local_path(s3_key: str) -> Path:
    """Resolve a local filesystem path for an s3_key in dev mode."""
    base = Path(settings.BASE_DIR) / "local_board_storage"
    base.mkdir(parents=True, exist_ok=True)
    # Flatten the key into a safe filename: boards/abc12345/file.brd → boards_abc12345_file.brd
    safe_name = s3_key.replace("/", "_")
    return base / safe_name


# ── Public API ─────────────────────────────────────────────────────────────

def upload_board_file(s3_key: str, file_bytes: bytes) -> None:
    """
    Upload raw board file bytes to storage.
    In production: private S3 bucket.
    In dev (USE_S3=False): local filesystem under local_board_storage/.
    Called only during admin upload flow.
    """
    if _use_s3():
        client = _get_s3()
        client.put_object(
            Bucket=settings.AWS_STORAGE_BUCKET_NAME,
            Key=s3_key,
            Body=file_bytes,
            ServerSideEncryption="AES256",
        )
        logger.info(
            "Uploaded board file to s3://%s/%s (%d bytes)",
            settings.AWS_STORAGE_BUCKET_NAME, s3_key, len(file_bytes),
        )
    else:
        path = _local_path(s3_key)
        path.write_bytes(file_bytes)
        logger.info("DEV: Saved board file to %s (%d bytes)", path, len(file_bytes))


def read_board_file(s3_key: str) -> bytes:
    """
    Read raw board file bytes for server-side parsing.
    The bytes NEVER leave the server — only parsed JSON is sent to clients.
    Called by the Celery parse task and the board view endpoint (cache miss).
    """
    if _use_s3():
        from botocore.exceptions import ClientError
        client = _get_s3()
        try:
            response = client.get_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=s3_key,
            )
            return response["Body"].read()
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            logger.error("S3 read failed for key %s: %s", s3_key, error_code)
            raise
    else:
        path = _local_path(s3_key)
        if not path.exists():
            raise FileNotFoundError(
                f"DEV: Local board file not found: {path}\n"
                f"Run: python manage.py seed_board <path-to-brd-file>"
            )
        return path.read_bytes()


def delete_board_file(s3_key: str) -> None:
    """
    Permanently delete a board file from storage.
    Called only by admin delete endpoint.
    """
    if _use_s3():
        from botocore.exceptions import ClientError
        client = _get_s3()
        try:
            client.delete_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=s3_key,
            )
            logger.info(
                "Deleted s3://%s/%s", settings.AWS_STORAGE_BUCKET_NAME, s3_key
            )
        except ClientError as exc:
            logger.error("S3 delete failed for key %s: %s", s3_key, exc)
            raise
    else:
        path = _local_path(s3_key)
        if path.exists():
            path.unlink()
            logger.info("DEV: Deleted local board file %s", path)


def board_file_exists(s3_key: str) -> bool:
    """Check if a board file exists in storage without downloading it."""
    if _use_s3():
        from botocore.exceptions import ClientError
        client = _get_s3()
        try:
            client.head_object(
                Bucket=settings.AWS_STORAGE_BUCKET_NAME,
                Key=s3_key,
            )
            return True
        except ClientError:
            return False
    else:
        return _local_path(s3_key).exists()
