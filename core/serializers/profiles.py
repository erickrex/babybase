"""Profile serializers for BabyBase."""

from django.contrib.auth import get_user_model
from rest_framework import serializers

User = get_user_model()


class ProfileSerializer(serializers.ModelSerializer):
    """Serializer for user profile (GET/PATCH /api/v1/profile/me/)."""

    class Meta:
        model = User
        fields = ["id", "email", "first_name", "role_in_pregnancy", "age", "gender", "nationality"]
        read_only_fields = ["id", "email"]

    def validate_role_in_pregnancy(self, value: str) -> str:
        valid_choices = ["father", "mother"]
        if value and value not in valid_choices:
            raise serializers.ValidationError(f"Must be one of: {', '.join(valid_choices)}")
        return value
