"""
Board API views.

/api/boards/              - Technician: list enabled boards
/api/boards/{id}/         - Technician: board metadata
/api/boards/{id}/view/    - Technician: ★ parsed board JSON for rendering
"""
import logging
from pathlib import Path

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from apps.accounts.permissions import CanViewBoard, HasActiveSubscription

from .models import BoardFile, BoardStatus, ParseStatus
from .serializers import BoardFileDetailSerializer, BoardFileListSerializer
from .tasks import parse_board_task

logger = logging.getLogger(__name__)


class BoardViewRateThrottle(UserRateThrottle):
    scope = "board_view"


# ---------------------------------------------------------------------------
# Technician endpoints
# ---------------------------------------------------------------------------

class BoardListView(APIView):
    """
    GET /api/boards/

    Returns boards visible to the current user.
    - Technicians see only enabled + restricted (if tier matches) boards.
    - Admins see all boards.

    Supports filtering via query params:
      ?category=cellphone
      ?brand=Apple
      ?search=iphone
      ?status=enabled   (admin only)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        if request.user.is_admin:
            qs = BoardFile.objects.all()
        else:
            # Technicians only see enabled + restricted boards
            qs = BoardFile.objects.filter(
                status__in=[BoardStatus.ENABLED, BoardStatus.RESTRICTED]
            )

        # Filtering
        category = request.query_params.get("category")
        if category:
            qs = qs.filter(category=category)

        brand = request.query_params.get("brand")
        if brand:
            qs = qs.filter(brand__icontains=brand)

        search = request.query_params.get("search")
        if search:
            qs = qs.filter(name__icontains=search) | qs.filter(
                model_number__icontains=search
            )

        # Admins can filter by status
        if request.user.is_admin:
            status_filter = request.query_params.get("status")
            if status_filter:
                qs = qs.filter(status=status_filter)

        serializer = BoardFileListSerializer(qs, many=True)
        return Response({"data": serializer.data})


class BoardDetailView(APIView):
    """
    GET /api/boards/{id}/

    Returns board metadata — no raw file, no parsed JSON.
    Unsubscribed technicians can see metadata but NOT render.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request: Request, pk: int) -> Response:
        board = get_object_or_404(BoardFile, pk=pk)

        # Non-admin: hide disabled boards entirely
        if not request.user.is_admin and board.status == BoardStatus.DISABLED:
            return Response({"error": "Board not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = BoardFileDetailSerializer(board)
        return Response({"data": serializer.data})


class BoardViewEndpoint(APIView):
    """
    GET /api/boards/{id}/view/

    ★ THE CRITICAL ENDPOINT ★

    Returns parsed board JSON for rendering in the browser.
    Auth chain (all must pass):
      1. Authenticated (JWT)
      2. Not suspended
      3. Has active subscription (or is admin)
      4. Board is accessible (CanViewBoard object-level check)
      5. Board parse_status is 'success'

    Flow:
      1. Check Redis cache (hit → return immediately)
      2. Cache miss → dispatch Celery reparse task → return 202 (UI polls)

    NEVER returns raw file bytes, s3_key, or anything that could
    be used to reconstruct the original board file.
    """
    permission_classes = [IsAuthenticated, HasActiveSubscription, CanViewBoard]
    throttle_classes = [BoardViewRateThrottle]

    def get(self, request: Request, pk: int) -> Response:
        board = get_object_or_404(BoardFile, pk=pk)

        # Object-level permission check (CanViewBoard)
        self.check_object_permissions(request, board)

        # Board must be successfully parsed
        if board.parse_status == ParseStatus.PENDING:
            return Response(
                {"error": "Board is queued for processing. Check back shortly."},
                status=status.HTTP_202_ACCEPTED,
            )
        if board.parse_status == ParseStatus.PARSING:
            return Response(
                {"error": "Board is currently being processed. Check back shortly."},
                status=status.HTTP_202_ACCEPTED,
            )
        if board.parse_status == ParseStatus.FAILED:
            return Response(
                {"error": "Board could not be processed. Please contact support."},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        # Check Redis cache first
        cached = cache.get(board.redis_cache_key)
        if cached:
            board.record_view()
            return Response({"data": cached})

        # Cache miss — dispatch async reparse rather than blocking the request.
        # This keeps response time fast; the UI polls on 202 until the cache is warm.
        logger.warning(
            "Cache miss for board %d (%s) — dispatching async reparse",
            board.pk,
            board.original_filename,
        )
        board.mark_parsing()
        parse_board_task.delay(board.pk)
        return Response(
            {"error": "Board data is being prepared. Check back shortly."},
            status=status.HTTP_202_ACCEPTED,
        )
