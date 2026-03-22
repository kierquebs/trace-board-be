"""
Tests for /api/boards/* endpoints.

Critical invariant: the /view/ endpoint must NEVER return raw file bytes,
s3_key, content_hash, or any data that could reconstruct the original file.
"""
import pytest
from unittest.mock import patch

from apps.boards.models import BoardFile, BoardStatus


@pytest.mark.django_db
class TestBoardList:
    url = "/api/boards/"

    def test_technician_sees_enabled_boards(self, technician_client, enabled_board):
        res = technician_client.get(self.url)
        assert res.status_code == 200
        ids = [b["id"] for b in res.json()["data"]]
        assert enabled_board.pk in ids

    def test_technician_does_not_see_disabled(self, technician_client, disabled_board):
        res = technician_client.get(self.url)
        ids = [b["id"] for b in res.json()["data"]]
        assert disabled_board.pk not in ids

    def test_admin_sees_all_boards(self, admin_client, enabled_board, disabled_board):
        res = admin_client.get(self.url)
        ids = [b["id"] for b in res.json()["data"]]
        assert enabled_board.pk in ids
        assert disabled_board.pk in ids

    def test_unauthenticated_returns_401(self, api_client):
        res = api_client.get(self.url)
        assert res.status_code == 401

    def test_response_never_contains_s3_key(self, technician_client, enabled_board):
        """Security check: s3_key must never appear in any board list response."""
        res = technician_client.get(self.url)
        response_text = res.content.decode()
        assert "s3_key" not in response_text
        assert enabled_board.s3_key not in response_text

    def test_filter_by_category(self, technician_client, db):
        from tests.conftest import BoardFileFactory, AdminUserFactory
        admin = AdminUserFactory()
        BoardFileFactory(uploaded_by=admin, category="cellphone", status=BoardStatus.ENABLED)
        BoardFileFactory(uploaded_by=admin, category="laptop", status=BoardStatus.ENABLED)

        res = technician_client.get(self.url + "?category=laptop")
        data = res.json()["data"]
        assert all(b["category"] == "laptop" for b in data)


@pytest.mark.django_db
class TestBoardView:
    """Tests for GET /api/boards/{id}/view/ — the critical rendering endpoint."""

    def _url(self, board_id):
        return f"/api/boards/{board_id}/view/"

    def test_unsubscribed_cannot_view_board(self, unsubscribed_client, enabled_board):
        res = unsubscribed_client.get(self._url(enabled_board.pk))
        assert res.status_code == 403

    def test_unauthenticated_cannot_view_board(self, api_client, enabled_board):
        res = api_client.get(self._url(enabled_board.pk))
        assert res.status_code == 401

    def test_subscribed_can_view_enabled_board(self, technician_client, enabled_board):
        """Board with status=success and Redis cache hit returns parsed JSON."""
        mock_board_json = {
            "format": "brd2",
            "width": 1000.0,
            "height": 800.0,
            "outline": [],
            "parts": [{"id": "U1", "name": "U1", "side": "top",
                        "bounds": {"x": 0, "y": 0, "width": 50, "height": 50},
                        "part_type": "", "value": "", "description": ""}],
            "pins": [],
            "nails": [],
            "nets": [],
        }

        with patch("django.core.cache.cache.get", return_value=mock_board_json):
            res = technician_client.get(self._url(enabled_board.pk))

        assert res.status_code == 200
        data = res.json()["data"]
        assert "format" in data
        assert "parts" in data
        assert "pins" in data
        assert "nets" in data

    def test_response_never_contains_s3_key(self, technician_client, enabled_board):
        """CRITICAL: s3_key must NEVER appear in /view/ response."""
        mock_json = {"format": "brd2", "width": 100, "height": 100,
                     "outline": [], "parts": [], "pins": [], "nails": [], "nets": []}

        with patch("django.core.cache.cache.get", return_value=mock_json):
            res = technician_client.get(self._url(enabled_board.pk))

        response_text = res.content.decode()
        assert "s3_key" not in response_text
        assert enabled_board.s3_key not in response_text
        assert enabled_board.content_hash not in response_text

    def test_pending_board_returns_202(self, technician_client, db):
        from tests.conftest import BoardFileFactory, AdminUserFactory
        admin = AdminUserFactory()
        board = BoardFileFactory(
            uploaded_by=admin,
            parse_status="pending",
            status=BoardStatus.ENABLED,
        )
        res = technician_client.get(self._url(board.pk))
        assert res.status_code == 202

    def test_failed_board_returns_422(self, technician_client, db):
        from tests.conftest import BoardFileFactory, AdminUserFactory
        admin = AdminUserFactory()
        board = BoardFileFactory(
            uploaded_by=admin,
            parse_status="failed",
            status=BoardStatus.ENABLED,
        )
        res = technician_client.get(self._url(board.pk))
        assert res.status_code == 422

    def test_disabled_board_returns_403(self, technician_client, disabled_board):
        res = technician_client.get(self._url(disabled_board.pk))
        assert res.status_code in (403, 404)

    def test_admin_can_view_disabled_board(self, admin_client, disabled_board):
        mock_json = {"format": "brd2", "width": 100, "height": 100,
                     "outline": [], "parts": [], "pins": [], "nails": [], "nets": []}
        with patch("django.core.cache.cache.get", return_value=mock_json):
            res = admin_client.get(self._url(disabled_board.pk))
        assert res.status_code == 200
