"""Swipe and match serializers for BabyBase."""

from rest_framework import serializers

from core.models import SwipeAction


class SwipeSerializer(serializers.Serializer):
    """Serializer for swipe creation (POST /api/v1/swipes/)."""

    name_id = serializers.UUIDField()
    action = serializers.ChoiceField(choices=SwipeAction.choices)
    deck_id = serializers.UUIDField(required=False, allow_null=True)


class SwipeResponseSerializer(serializers.Serializer):
    """Serializer for swipe response data."""

    id = serializers.UUIDField()
    name_id = serializers.UUIDField()
    action = serializers.CharField()
    created_at = serializers.DateTimeField()


class MatchNameSerializer(serializers.Serializer):
    """Serializer for name details within a match."""

    id = serializers.UUIDField()
    canonical_name = serializers.CharField()
    display_name = serializers.CharField()
    gender_usage = serializers.ListField()
    origin_backgrounds = serializers.ListField()
    languages = serializers.ListField()
    length_category = serializers.CharField()
    age_style_category = serializers.CharField()
    historical_significance_score = serializers.FloatField()
    semantic_summary = serializers.CharField()


class MatchSerializer(serializers.Serializer):
    """Serializer for a mutual match in list/detail responses."""

    id = serializers.UUIDField()
    name = MatchNameSerializer()
    matched_at = serializers.DateTimeField()
    match_strength_score = serializers.FloatField()
    status = serializers.CharField()
    removal_requested_by = serializers.SerializerMethodField()
    removal_pending = serializers.SerializerMethodField()

    def get_removal_requested_by(self, obj) -> str | None:
        """Return the id of the user who requested removal, or None."""
        return str(obj.removal_requested_by_id) if obj.removal_requested_by_id else None

    def get_removal_pending(self, obj) -> bool:
        """True when a removal request is awaiting partner approval."""
        return obj.removal_requested_by_id is not None


class MatchDetailSerializer(serializers.Serializer):
    """Serializer for match detail with semantic fit breakdown."""

    id = serializers.UUIDField()
    name = MatchNameSerializer()
    matched_at = serializers.DateTimeField()
    match_strength_score = serializers.FloatField()
    status = serializers.CharField()
    semantic_fit_breakdown = serializers.DictField()


class ShortlistSerializer(serializers.Serializer):
    """Serializer for adding a match to the shortlist."""

    name_id = serializers.UUIDField()


class ShortlistRemovalSerializer(serializers.Serializer):
    """Serializer for shortlist removal-request actions.

    decision controls the two-step removal flow:
    - omitted/null: request removal (or approve if partner already requested)
    - "cancel": requester withdraws their own pending request
    - "reject": the other partner declines a pending request
    """

    name_id = serializers.UUIDField()
    decision = serializers.ChoiceField(
        choices=["cancel", "reject"], required=False, allow_null=True
    )


class SimilarNameSerializer(serializers.Serializer):
    """Serializer for similar name results from Qdrant."""

    name_id = serializers.CharField()
    canonical_name = serializers.CharField()
    score = serializers.FloatField()
    origin_backgrounds = serializers.SerializerMethodField()
    gender_usage = serializers.SerializerMethodField()
    length_category = serializers.SerializerMethodField()
    age_style_category = serializers.SerializerMethodField()

    def get_origin_backgrounds(self, obj) -> list:
        return obj.get("payload", {}).get("origin_backgrounds", [])

    def get_gender_usage(self, obj) -> list:
        return obj.get("payload", {}).get("gender_usage", [])

    def get_length_category(self, obj) -> str:
        return obj.get("payload", {}).get("length_category", "")

    def get_age_style_category(self, obj) -> str:
        return obj.get("payload", {}).get("age_style_category", "")
