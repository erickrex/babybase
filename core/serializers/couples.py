"""Couple serializers for BabyBase."""

from rest_framework import serializers


class CoupleInviteSerializer(serializers.Serializer):
    """Serializer for partner invite (POST /api/v1/couples/invite/)."""

    partner_email = serializers.EmailField()

    def validate_partner_email(self, value: str) -> str:
        email = value.lower()
        # Can't invite yourself
        request = self.context.get("request")
        if request and request.user.email.lower() == email:
            raise serializers.ValidationError("You cannot invite yourself.")
        return email
