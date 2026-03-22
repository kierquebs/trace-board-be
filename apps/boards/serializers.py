"""
Board serializers.

CRITICAL RULE: s3_key, content_hash, and parse_error (for technicians)
must NEVER appear in any serializer exposed to technician-facing endpoints.
Only BoardFileAdminSerializer (used exclusively by admin endpoints) may
include operational fields.
"""
from rest_framework import serializers

from .models import BoardFile


class BoardFileListSerializer(serializers.ModelSerializer):
    """
    Minimal serializer for board list/browse pages.
    Returned by GET /api/boards/ — visible to all authenticated users.
    No s3_key, no content_hash, no parse_error.
    """

    class Meta:
        model = BoardFile
        fields = [
            "id",
            "name",
            "brand",
            "model_number",
            "category",
            "tags",
            "format",
            "part_count",
            "pin_count",
            "net_count",
            "parse_status",
            "status",
            "uploaded_at",
        ]
        # status visible so frontend can show paywall for restricted boards
        read_only_fields = fields


class BoardFileDetailSerializer(BoardFileListSerializer):
    """
    Richer serializer for the board detail page metadata.
    Still NO raw file access fields.
    """

    class Meta(BoardFileListSerializer.Meta):
        fields = BoardFileListSerializer.Meta.fields + [
            "description",
            "view_count",
            "last_viewed_at",
        ]
        read_only_fields = fields


# ---------------------------------------------------------------------------
# Admin serializers — include operational/internal fields
# ---------------------------------------------------------------------------

class BoardFileAdminListSerializer(serializers.ModelSerializer):
    """
    Full board info for admin list view.
    Includes operational fields (parse_error, view_count etc.) but
    still excludes s3_key — admins don't need the raw S3 key.
    """
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username", read_only=True, allow_null=True
    )

    class Meta:
        model = BoardFile
        fields = [
            "id",
            "name",
            "original_filename",
            "brand",
            "model_number",
            "category",
            "tags",
            "status",
            "min_tier",
            "format",
            "file_size",
            "part_count",
            "pin_count",
            "net_count",
            "parse_status",
            "parse_error",
            "view_count",
            "last_viewed_at",
            "uploaded_by_username",
            "uploaded_at",
            "updated_at",
        ]
        read_only_fields = [
            "id", "original_filename", "format", "file_size",
            "part_count", "pin_count", "net_count",
            "parse_status", "parse_error", "view_count",
            "last_viewed_at", "uploaded_by_username",
            "uploaded_at", "updated_at",
        ]


class BoardFileAdminUpdateSerializer(serializers.ModelSerializer):
    """Admin PATCH — only editable metadata fields."""

    class Meta:
        model = BoardFile
        fields = ["name", "description", "brand", "model_number", "category", "tags", "status", "min_tier"]


class BoardFileUploadSerializer(serializers.Serializer):
    """Validates the multipart upload request from admin."""
    file = serializers.FileField()
    name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True)
    brand = serializers.CharField(max_length=100, required=False, allow_blank=True)
    model_number = serializers.CharField(max_length=100, required=False, allow_blank=True)
    category = serializers.ChoiceField(
        choices=["cellphone", "laptop", "tablet", "desktop", "other"],
        default="cellphone",
    )
    tags = serializers.ListField(
        child=serializers.CharField(), required=False, default=list
    )
