"""
Admin panel API endpoints.

All views here require IsAdmin permission.
Mounted at /api/admin/*
"""
import logging
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404
from rest_framework import status, serializers
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsAdmin
from apps.boards.models import BoardFile, BoardStatus
from apps.boards.serializers import (
    BoardFileAdminListSerializer,
    BoardFileAdminUpdateSerializer,
    BoardFileUploadSerializer,
)
from apps.boards.storage import delete_board_file, upload_board_file
from apps.boards.tasks import invalidate_board_cache, parse_board_task
from apps.billing.models import Subscription

User = get_user_model()
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Inline serializers for admin user management
# ---------------------------------------------------------------------------

class AdminUserListSerializer(serializers.ModelSerializer):
    subscription_status = serializers.SerializerMethodField()
    subscription_plan = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "role",
            "company_name", "phone",
            "is_suspended", "is_active",
            "subscription_status", "subscription_plan",
            "date_joined", "last_login",
        ]

    def get_subscription_status(self, obj) -> str | None:
        try:
            return obj.subscription.status
        except Exception:
            return None

    def get_subscription_plan(self, obj) -> str | None:
        try:
            return obj.subscription.plan.slug
        except Exception:
            return None


class AdminUserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["is_suspended", "is_active"]


# ---------------------------------------------------------------------------
# Board management
# ---------------------------------------------------------------------------

class AdminBoardListView(APIView):
    """
    GET  /api/admin/boards/  — All boards including disabled
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request: Request) -> Response:
        qs = BoardFile.objects.select_related("uploaded_by").all()

        # Filtering
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)

        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search)

        serializer = BoardFileAdminListSerializer(qs, many=True)
        return Response({"data": serializer.data})


class AdminBoardUploadView(APIView):
    """
    POST /api/admin/boards/upload/

    Accepts multipart/form-data with:
      - file: the board file
      - name, description, brand, model_number, category, tags
    """
    permission_classes = [IsAuthenticated, IsAdmin]
    parser_classes = [MultiPartParser]

    def post(self, request: Request) -> Response:
        from django.conf import settings

        serializer = BoardFileUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        file = data["file"]

        # Validate extension
        ext = Path(file.name).suffix.lower()
        allowed = getattr(settings, "BOARD_FILE_ALLOWED_EXTENSIONS", {".brd", ".bv", ".bvr", ".fz", ".asc", ".cad", ".cst"})
        if ext not in allowed:
            return Response(
                {"error": f"Unsupported file format '{ext}'. Allowed: {', '.join(sorted(allowed))}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate size
        max_mb = getattr(settings, "BOARD_FILE_MAX_SIZE_MB", 50)
        if file.size > max_mb * 1024 * 1024:
            return Response(
                {"error": f"File too large. Maximum size is {max_mb}MB."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        file_bytes = file.read()
        content_hash = BoardFile.compute_hash(file_bytes)

        # Duplicate check
        existing = BoardFile.objects.filter(content_hash=content_hash).first()
        if existing:
            return Response(
                {
                    "error": "This exact file has already been uploaded.",
                    "existing_board_id": existing.pk,
                    "existing_board_name": existing.name,
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Detect format for the DB record (full parse happens async)
        from apps.boards.parsers import detect_format
        fmt = detect_format(file_bytes, file.name)

        # Upload to S3
        s3_key = BoardFile.build_s3_key(content_hash, file.name)
        upload_board_file(s3_key, file_bytes)

        # Create DB record
        board = BoardFile.objects.create(
            uploaded_by=request.user,
            name=data.get("name") or file.name,
            original_filename=file.name,
            s3_key=s3_key,
            content_hash=content_hash,
            file_size=len(file_bytes),
            format=fmt.value,
            status=BoardStatus.ENABLED,
            description=data.get("description", ""),
            brand=data.get("brand", ""),
            model_number=data.get("model_number", ""),
            category=data.get("category", "cellphone"),
            tags=data.get("tags", []),
        )

        # Trigger async parse
        parse_board_task.delay(board.pk)

        logger.info(
            "Admin %s uploaded board '%s' (id=%d, format=%s)",
            request.user.username, board.name, board.pk, fmt.value,
        )

        return Response(
            {"data": BoardFileAdminListSerializer(board).data},
            status=status.HTTP_201_CREATED,
        )


class AdminBoardDetailView(APIView):
    """
    GET    /api/admin/boards/{id}/   — Board detail
    PATCH  /api/admin/boards/{id}/   — Update metadata / status
    DELETE /api/admin/boards/{id}/   — Delete board + S3 file
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request: Request, pk: int) -> Response:
        board = get_object_or_404(BoardFile, pk=pk)
        serializer = BoardFileAdminListSerializer(board)
        return Response({"data": serializer.data})

    def patch(self, request: Request, pk: int) -> Response:
        board = get_object_or_404(BoardFile, pk=pk)
        serializer = BoardFileAdminUpdateSerializer(board, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"data": BoardFileAdminListSerializer(board).data})

    def delete(self, request: Request, pk: int) -> Response:
        board = get_object_or_404(BoardFile, pk=pk)

        # Remove from Redis cache
        cache.delete(board.redis_cache_key)

        # Delete from S3
        try:
            delete_board_file(board.s3_key)
        except Exception as exc:
            logger.error("S3 delete failed for board %d: %s", pk, exc)
            # Continue — remove DB record even if S3 delete fails

        board_name = board.name
        board.delete()

        logger.info("Admin %s deleted board '%s' (id=%d)", request.user.username, board_name, pk)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AdminBoardReparseView(APIView):
    """POST /api/admin/boards/{id}/reparse/"""
    permission_classes = [IsAuthenticated, IsAdmin]

    def post(self, request: Request, pk: int) -> Response:
        board = get_object_or_404(BoardFile, pk=pk)

        # Invalidate cache
        invalidate_board_cache.delay(board.content_hash)

        # Re-trigger parse
        board.parse_status = "pending"
        board.parse_error = ""
        board.save(update_fields=["parse_status", "parse_error"])
        parse_board_task.delay(board.pk)

        return Response({"data": {"detail": f"Re-parse queued for '{board.name}'."}})


# ---------------------------------------------------------------------------
# User management
# ---------------------------------------------------------------------------

class AdminUserListView(APIView):
    """GET /api/admin/users/"""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request: Request) -> Response:
        qs = User.objects.filter(role="technician").select_related("subscription__plan")

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(username__icontains=search) | qs.filter(email__icontains=search)

        is_suspended = request.query_params.get("suspended")
        if is_suspended is not None:
            qs = qs.filter(is_suspended=is_suspended.lower() == "true")

        serializer = AdminUserListSerializer(qs, many=True)
        return Response({"data": serializer.data})


class AdminUserDetailView(APIView):
    """
    GET   /api/admin/users/{id}/  — User detail
    PATCH /api/admin/users/{id}/  — Suspend/activate
    """
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request: Request, pk: int) -> Response:
        user = get_object_or_404(User, pk=pk, role="technician")
        serializer = AdminUserListSerializer(user)
        return Response({"data": serializer.data})

    def patch(self, request: Request, pk: int) -> Response:
        user = get_object_or_404(User, pk=pk, role="technician")
        serializer = AdminUserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"data": AdminUserListSerializer(user).data})


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------

class AdminAnalyticsOverviewView(APIView):
    """GET /api/admin/analytics/overview/"""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request: Request) -> Response:
        total_technicians = User.objects.filter(role="technician").count()
        active_subscribers = Subscription.objects.filter(status__in=["active", "trial"]).count()

        mrr_data = (
            Subscription.objects.filter(status="active")
            .select_related("plan")
            .aggregate(mrr=Sum("plan__price_php"))
        )
        mrr = mrr_data["mrr"] or 0

        total_boards = BoardFile.objects.count()
        enabled_boards = BoardFile.objects.filter(status="enabled").count()

        return Response({
            "data": {
                "total_technicians": total_technicians,
                "active_subscribers": active_subscribers,
                "mrr_php": float(mrr),
                "total_boards": total_boards,
                "enabled_boards": enabled_boards,
            }
        })


class AdminAnalyticsPopularBoardsView(APIView):
    """GET /api/admin/analytics/popular-boards/"""
    permission_classes = [IsAuthenticated, IsAdmin]

    def get(self, request: Request) -> Response:
        boards = (
            BoardFile.objects.filter(status="enabled")
            .order_by("-view_count")[:20]
            .values("id", "name", "brand", "category", "view_count", "last_viewed_at")
        )
        return Response({"data": list(boards)})
