from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers

User = get_user_model()


class RegisterSerializer(serializers.ModelSerializer):
    """Technician self-registration. Role is always set to 'technician'."""

    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "password",
            "password_confirm",
            "phone",
            "company_name",
        ]
        read_only_fields = ["id"]

    def validate_email(self, value: str) -> str:
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate(self, attrs: dict) -> dict:
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return attrs

    def create(self, validated_data: dict) -> User:
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data["email"],
            password=validated_data["password"],
            phone=validated_data.get("phone", ""),
            company_name=validated_data.get("company_name", ""),
            role="technician",  # Always technician on self-register
        )


class UserProfileSerializer(serializers.ModelSerializer):
    """
    Safe public representation of the current user.
    Returned by GET /api/auth/me/ — never includes password or s3 details.
    """

    has_active_subscription = serializers.BooleanField(read_only=True)
    subscription_tier = serializers.CharField(read_only=True, allow_null=True)

    class Meta:
        model = User
        fields = [
            "id",
            "username",
            "email",
            "role",
            "phone",
            "company_name",
            "is_suspended",
            "has_active_subscription",
            "subscription_tier",
            "date_joined",
        ]
        read_only_fields = ["id", "role", "is_suspended", "date_joined"]


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])

    def validate_old_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value
