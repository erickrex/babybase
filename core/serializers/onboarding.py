"""Onboarding serializers for BabyBase."""

from rest_framework import serializers

from core.models import BabyGender, HistoricalImportance, NameAge, NameLength


class OnboardingPreferencesSerializer(serializers.Serializer):
    """Serializer for onboarding preferences (POST /api/v1/onboarding/preferences/)."""

    preferred_name_backgrounds = serializers.ListField(
        child=serializers.CharField(max_length=100),
        allow_empty=False,
    )
    preferred_name_age = serializers.ChoiceField(choices=NameAge.choices)
    baby_gender_preference = serializers.ChoiceField(choices=BabyGender.choices)
    preferred_name_length = serializers.ChoiceField(choices=NameLength.choices)
    historical_importance = serializers.ChoiceField(choices=HistoricalImportance.choices)
    residence_country = serializers.CharField(max_length=2, required=False, allow_blank=True)

    def validate_residence_country(self, value: str) -> str:
        if value and len(value) != 2:
            raise serializers.ValidationError("Must be a 2-letter ISO 3166-1 alpha-2 country code.")
        return value.upper() if value else ""
