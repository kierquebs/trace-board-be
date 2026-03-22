from django.conf import settings
from django.db import models


class AnnotationType(models.TextChoices):
    NOTE = "note", "Note"
    MARKER = "marker", "Marker"
    HIGHLIGHT = "highlight", "Highlight"


class Annotation(models.Model):
    """
    A technician's personal annotation on a specific board.

    Annotations are private per-user — one technician cannot see
    another technician's annotations. Admins can view all.

    Position is stored in board coordinate space (same units as
    the parsed board JSON) so annotations remain accurate across
    different zoom levels and viewport sizes.
    """

    board = models.ForeignKey(
        "boards.BoardFile",
        on_delete=models.CASCADE,
        related_name="annotations",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="annotations",
    )

    annotation_type = models.CharField(
        max_length=20,
        choices=AnnotationType.choices,
        default=AnnotationType.NOTE,
    )

    # Board-space coordinates
    x = models.FloatField()
    y = models.FloatField()

    text = models.TextField(blank=True)
    color = models.CharField(max_length=7, default="#FF69B4")  # Hex color

    # Optional references to board entities
    component_ref = models.CharField(
        max_length=50,
        blank=True,
        help_text="Part name this annotation is attached to (e.g. 'U1')",
    )
    net_ref = models.CharField(
        max_length=100,
        blank=True,
        help_text="Net name this annotation refers to",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["board", "user"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.username} on board {self.board_id}: {self.text[:50]}"
