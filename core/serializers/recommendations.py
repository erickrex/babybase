"""Recommendation serializers for BabyBase."""

from rest_framework import serializers

from core.models import DeckMode
from core.serializers.swipes import MatchNameSerializer


class GenerateDeckSerializer(serializers.Serializer):
    """Serializer for deck generation request (POST /api/v1/recommendations/deck/)."""

    mode = serializers.ChoiceField(
        choices=DeckMode.choices,
        default=DeckMode.BEST_MATCH,
        required=False,
    )
    force_refresh = serializers.BooleanField(default=False, required=False)


class DeckItemSerializer(serializers.Serializer):
    """Serializer for a single deck item in the response."""

    id = serializers.UUIDField()
    name_id = serializers.UUIDField()
    name = MatchNameSerializer(read_only=True)
    rank = serializers.IntegerField()
    retrieval_score = serializers.FloatField()
    rerank_score = serializers.FloatField()
    explanation_summary = serializers.CharField()


class DeckSerializer(serializers.Serializer):
    """Serializer for a recommendation deck response."""

    id = serializers.UUIDField()
    mode = serializers.CharField()
    created_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField()
    items = DeckItemSerializer(many=True)
