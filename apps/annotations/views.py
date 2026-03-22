from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers

from apps.accounts.permissions import HasActiveSubscription
from apps.boards.models import BoardFile, BoardStatus

from .models import Annotation


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

class AnnotationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Annotation
        fields = [
            "id",
            "annotation_type",
            "x",
            "y",
            "text",
            "color",
            "component_ref",
            "net_ref",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class BoardAnnotationListView(APIView):
    """
    GET  /api/boards/{board_id}/annotations/ — list MY annotations on this board
    POST /api/boards/{board_id}/annotations/ — create annotation
    """
    permission_classes = [IsAuthenticated, HasActiveSubscription]

    def _get_accessible_board(self, board_id: int, user):
        board = get_object_or_404(BoardFile, pk=board_id)
        if not user.is_admin and board.status == BoardStatus.DISABLED:
            from rest_framework.exceptions import NotFound
            raise NotFound
        return board

    def get(self, request: Request, board_id: int) -> Response:
        self._get_accessible_board(board_id, request.user)
        annotations = Annotation.objects.filter(board_id=board_id, user=request.user)
        serializer = AnnotationSerializer(annotations, many=True)
        return Response({"data": serializer.data})

    def post(self, request: Request, board_id: int) -> Response:
        self._get_accessible_board(board_id, request.user)
        serializer = AnnotationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(board_id=board_id, user=request.user)
        return Response({"data": serializer.data}, status=status.HTTP_201_CREATED)


class AnnotationDetailView(APIView):
    """
    PATCH  /api/annotations/{id}/ — update MY annotation
    DELETE /api/annotations/{id}/ — delete MY annotation
    """
    permission_classes = [IsAuthenticated, HasActiveSubscription]

    def _get_own_annotation(self, pk: int, user):
        return get_object_or_404(Annotation, pk=pk, user=user)

    def patch(self, request: Request, pk: int) -> Response:
        annotation = self._get_own_annotation(pk, request.user)
        serializer = AnnotationSerializer(annotation, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"data": serializer.data})

    def delete(self, request: Request, pk: int) -> Response:
        annotation = self._get_own_annotation(pk, request.user)
        annotation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
