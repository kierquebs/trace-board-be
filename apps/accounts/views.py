from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .serializers import ChangePasswordSerializer, RegisterSerializer, UserProfileSerializer

User = get_user_model()


# ── Custom JWT ─────────────────────────────────────────────────────────────────

class TraceBoardTokenSerializer(TokenObtainPairSerializer):
    """
    Extends simplejwt's serializer to:
      1. Embed role + subscription claims into the JWT payload
      2. Return user profile data alongside tokens in the response body

    JWT claims (accessible to the frontend without an extra /me/ call):
      role, is_admin, has_active_subscription, subscription_tier, is_suspended
    """

    @classmethod
    def get_token(cls, user) -> RefreshToken:
        token = super().get_token(user)
        token['role']                    = user.role
        token['is_admin']                = user.is_admin
        token['has_active_subscription'] = user.has_active_subscription
        token['is_suspended']            = user.is_suspended
        try:
            sub = user.subscription
            token['subscription_tier'] = sub.tier_slug if sub.is_active else None
        except Exception:
            token['subscription_tier'] = None
        return token

    def validate(self, attrs: dict) -> dict:
        data = super().validate(attrs)
        data['user'] = UserProfileSerializer(self.user).data
        return data


class LoginView(TokenObtainPairView):
    """
    POST /api/auth/login/

    Body: { "username": "...", "password": "..." }
       or { "email": "...", "password": "..." }

    Returns:
        {
          "data": {
            "access":  "<JWT access token>",
            "refresh": "<JWT refresh token>",
            "user": {
              "id", "username", "email", "role",
              "has_active_subscription", "subscription_tier",
              "is_suspended", ...
            }
          }
        }

    HTTP 403 if account is suspended (credentials valid, access denied).
    HTTP 401 if credentials invalid.
    """

    serializer_class = TraceBoardTokenSerializer

    def post(self, request: Request, *args, **kwargs) -> Response:
        # Support login by email as well as username
        # simplejwt requires the USERNAME_FIELD; map email → username if needed
        data = request.data.copy()
        email = (data.get('email') or '').strip().lower()
        if email and 'username' not in data:
            try:
                user_obj = User.objects.get(email__iexact=email)
                data = data.copy()
                data['username'] = user_obj.username
            except User.DoesNotExist:
                pass   # let simplejwt return its normal auth error

        serializer = self.get_serializer(data=data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc

        user = serializer.user
        if user.is_suspended:
            return Response(
                {'error': 'Account suspended. Please contact support.'},
                status=status.HTTP_403_FORBIDDEN,
            )

        return Response({'data': serializer.validated_data})


# ── Registration ───────────────────────────────────────────────────────────────

class RegisterView(APIView):
    """
    POST /api/auth/register/

    Open to anyone. Creates a technician account (role is always 'technician').
    Returns JWT tokens so the user is immediately logged in.
    """

    permission_classes = [AllowAny]

    def post(self, request: Request) -> Response:
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)
        # Embed the same custom claims as LoginView
        refresh['role']                    = user.role
        refresh['is_admin']                = user.is_admin
        refresh['has_active_subscription'] = user.has_active_subscription
        refresh['is_suspended']            = False
        refresh['subscription_tier']       = None

        return Response(
            {
                'data': {
                    'access':  str(refresh.access_token),
                    'refresh': str(refresh),
                    'user':    UserProfileSerializer(user).data,
                }
            },
            status=status.HTTP_201_CREATED,
        )


# ── Current user ───────────────────────────────────────────────────────────────

class MeView(APIView):
    """
    GET  /api/auth/me/  — current user profile + live subscription status
    PATCH /api/auth/me/ — update profile fields (phone, company_name)
    """

    permission_classes = [IsAuthenticated]

    def get(self, request: Request) -> Response:
        return Response({'data': UserProfileSerializer(request.user).data})

    def patch(self, request: Request) -> Response:
        serializer = UserProfileSerializer(
            request.user,
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'data': serializer.data})


# ── Password management ────────────────────────────────────────────────────────

class ChangePasswordView(APIView):
    """POST /api/auth/password/change/"""

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request},
        )
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data['new_password'])
        request.user.save(update_fields=['password'])
        return Response({'data': {'detail': 'Password updated successfully.'}})


class LogoutView(APIView):
    """
    POST /api/auth/logout/

    Blacklists the refresh token so it can no longer generate new access tokens.
    The client should discard both tokens from its storage.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request: Request) -> Response:
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {'error': 'refresh token required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except Exception:
            pass  # Already blacklisted or invalid — still return success
        return Response({'data': {'detail': 'Logged out successfully.'}})
