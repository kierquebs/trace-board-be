"""
Tests for /api/auth/* endpoints.
"""
import pytest
from django.urls import reverse


@pytest.mark.django_db
class TestRegister:
    url = "/api/auth/register/"

    def test_register_creates_technician(self, api_client):
        payload = {
            "username": "newtech",
            "email": "newtech@example.com",
            "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
        }
        res = api_client.post(self.url, payload)
        assert res.status_code == 201
        data = res.json()["data"]
        assert data["user"]["role"] == "technician"
        assert "access" in data
        assert "refresh" in data

    def test_register_returns_jwt_immediately(self, api_client):
        payload = {
            "username": "tech2",
            "email": "tech2@test.com",
            "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
        }
        res = api_client.post(self.url, payload)
        assert res.status_code == 201
        assert res.json()["data"]["access"]  # Logged in on register

    def test_register_rejects_mismatched_passwords(self, api_client):
        payload = {
            "username": "tech3",
            "email": "tech3@test.com",
            "password": "StrongPass123!",
            "password_confirm": "WrongPass123!",
        }
        res = api_client.post(self.url, payload)
        assert res.status_code == 400

    def test_register_rejects_duplicate_email(self, api_client, technician_user):
        payload = {
            "username": "newusername",
            "email": technician_user.email,  # Already taken
            "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
        }
        res = api_client.post(self.url, payload)
        assert res.status_code == 400

    def test_register_cannot_create_admin(self, api_client):
        """Public registration must always produce technician role."""
        payload = {
            "username": "sneakyadmin",
            "email": "sneaky@test.com",
            "password": "StrongPass123!",
            "password_confirm": "StrongPass123!",
            "role": "admin",  # Attempt to inject role
        }
        res = api_client.post(self.url, payload)
        assert res.status_code == 201
        assert res.json()["data"]["user"]["role"] == "technician"


@pytest.mark.django_db
class TestLogin:
    url = "/api/auth/login/"

    def test_login_returns_tokens(self, api_client, technician_user):
        res = api_client.post(self.url, {
            "username": technician_user.username,
            "password": "testpass123",
        })
        assert res.status_code == 200
        body = res.json()
        assert "access" in body["data"]
        assert "refresh" in body["data"]

    def test_login_rejects_wrong_password(self, api_client, technician_user):
        res = api_client.post(self.url, {
            "username": technician_user.username,
            "password": "wrongpassword",
        })
        assert res.status_code == 401

    def test_suspended_user_cannot_login(self, api_client, technician_user):
        technician_user.is_suspended = True
        technician_user.save()
        # Suspension is enforced at login — suspended users are rejected immediately
        res = api_client.post(self.url, {
            "username": technician_user.username,
            "password": "testpass123",
        })
        assert res.status_code == 403
        assert "error" in res.json()


@pytest.mark.django_db
class TestMe:
    url = "/api/auth/me/"

    def test_me_returns_profile(self, technician_client, subscribed_technician):
        res = technician_client.get(self.url)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["username"] == subscribed_technician.username
        assert data["role"] == "technician"
        assert data["has_active_subscription"] is True

    def test_me_unsubscribed_shows_no_subscription(self, unsubscribed_client):
        res = unsubscribed_client.get(self.url)
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["has_active_subscription"] is False
        assert data["subscription_tier"] is None

    def test_me_admin_has_access(self, admin_client):
        res = admin_client.get(self.url)
        assert res.status_code == 200
        assert res.json()["data"]["role"] == "admin"
        assert res.json()["data"]["has_active_subscription"] is True  # Admins always True

    def test_me_unauthenticated_returns_401(self, api_client):
        res = api_client.get(self.url)
        assert res.status_code == 401

    def test_me_patch_updates_profile(self, technician_client):
        res = technician_client.patch(self.url, {
            "company_name": "Manila Repair Shop",
            "phone": "+639171234567",
        })
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["company_name"] == "Manila Repair Shop"

    def test_me_cannot_change_role(self, technician_client):
        """Technicians must not be able to escalate their own role."""
        res = technician_client.patch(self.url, {"role": "admin"})
        assert res.status_code == 200
        # role field is read-only — it should remain technician
        assert res.json()["data"]["role"] == "technician"
