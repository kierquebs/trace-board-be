import hashlib
from pathlib import Path

from django.conf import settings
from django.db import models
from django.db.models import F


class BoardStatus(models.TextChoices):
    ENABLED = "enabled", "Enabled"
    DISABLED = "disabled", "Disabled"
    RESTRICTED = "restricted", "Restricted"


class ParseStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PARSING = "parsing", "Parsing"
    SUCCESS = "success", "Success"
    FAILED = "failed", "Failed"


class BoardCategory(models.TextChoices):
    CELLPHONE = "cellphone", "Cellphone"
    LAPTOP = "laptop", "Laptop"
    TABLET = "tablet", "Tablet"
    DESKTOP = "desktop", "Desktop"
    OTHER = "other", "Other"


class BoardFile(models.Model):
    """
    Represents a single uploaded PCB boardview file.

    Storage:
      - Raw file bytes live in a PRIVATE S3 bucket (s3_key).
      - The s3_key is NEVER sent to the client under any circumstances.
      - Only parsed JSON (stored in Redis) is served to technicians.

    Status flow (admin-controlled):
      enabled   → visible and viewable by subscribed technicians
      disabled  → hidden from all technicians (soft-delete)
      restricted → visible only to technicians on >= min_tier plan
    """

    # ------------------------------------------------------------------
    # Admin who uploaded this file
    # ------------------------------------------------------------------
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="uploaded_boards",
    )

    # ------------------------------------------------------------------
    # Display info — safe to expose to technicians
    # ------------------------------------------------------------------
    name = models.CharField(max_length=255, help_text="Display name, e.g. 'iPhone 15 Pro'")
    original_filename = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    brand = models.CharField(max_length=100, blank=True, db_index=True)
    model_number = models.CharField(max_length=100, blank=True)
    category = models.CharField(
        max_length=20,
        choices=BoardCategory.choices,
        default=BoardCategory.CELLPHONE,
        db_index=True,
    )
    tags = models.JSONField(default=list, blank=True)

    # ------------------------------------------------------------------
    # Admin control
    # ------------------------------------------------------------------
    status = models.CharField(
        max_length=20,
        choices=BoardStatus.choices,
        default=BoardStatus.ENABLED,
        db_index=True,
    )
    min_tier = models.CharField(
        max_length=20,
        default="starter",
        help_text="Minimum subscription tier required. Only applies when status=restricted.",
    )

    # ------------------------------------------------------------------
    # Storage — NEVER expose these fields to the API client
    # ------------------------------------------------------------------
    s3_key = models.CharField(max_length=500)
    content_hash = models.CharField(max_length=64, db_index=True, unique=True)
    file_size = models.IntegerField(help_text="File size in bytes")

    # ------------------------------------------------------------------
    # Parsed metadata — safe to expose
    # ------------------------------------------------------------------
    format = models.CharField(max_length=30, blank=True)
    part_count = models.IntegerField(null=True, blank=True)
    pin_count = models.IntegerField(null=True, blank=True)
    net_count = models.IntegerField(null=True, blank=True)
    parse_status = models.CharField(
        max_length=20,
        choices=ParseStatus.choices,
        default=ParseStatus.PENDING,
    )
    parse_error = models.TextField(blank=True)

    # ------------------------------------------------------------------
    # Timestamps
    # ------------------------------------------------------------------
    uploaded_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # ------------------------------------------------------------------
    # Usage tracking (safe to expose to admin analytics)
    # ------------------------------------------------------------------
    view_count = models.IntegerField(default=0)
    last_viewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-uploaded_at"]
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["brand", "status"]),
            models.Index(fields=["content_hash"]),
        ]
        verbose_name = "board file"
        verbose_name_plural = "board files"

    def __str__(self) -> str:
        return f"{self.name} ({self.format or 'unknown format'})"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def redis_cache_key(self) -> str:
        """Key used to store/retrieve parsed board JSON from Redis."""
        return f"board:parsed:{self.content_hash}"

    @property
    def is_viewable(self) -> bool:
        """Board is in a state that CAN be rendered (parse succeeded)."""
        return self.parse_status == ParseStatus.SUCCESS

    def record_view(self) -> None:
        """Increment view counter and update timestamp atomically."""
        from django.utils import timezone

        BoardFile.objects.filter(pk=self.pk).update(
            view_count=F("view_count") + 1,
            last_viewed_at=timezone.now(),
        )

    def mark_parsing(self) -> None:
        self.parse_status = ParseStatus.PARSING
        self.save(update_fields=["parse_status"])

    def mark_success(self, *, part_count: int, pin_count: int, net_count: int, fmt: str) -> None:
        self.parse_status = ParseStatus.SUCCESS
        self.part_count = part_count
        self.pin_count = pin_count
        self.net_count = net_count
        self.format = fmt
        self.parse_error = ""
        self.save(update_fields=["parse_status", "part_count", "pin_count", "net_count", "format", "parse_error"])

    def mark_failed(self, error: str) -> None:
        self.parse_status = ParseStatus.FAILED
        self.parse_error = error
        self.save(update_fields=["parse_status", "parse_error"])

    @staticmethod
    def compute_hash(file_bytes: bytes) -> str:
        return hashlib.sha256(file_bytes).hexdigest()

    @staticmethod
    def build_s3_key(content_hash: str, original_filename: str) -> str:
        ext = Path(original_filename).suffix.lower()
        return f"boards/{content_hash[:8]}/{content_hash}{ext}"
