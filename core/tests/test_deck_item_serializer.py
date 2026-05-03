"""Unit tests verifying DeckItemSerializer output contains all expected name fields."""

import uuid

import pytest

from core.serializers.recommendations import DeckItemSerializer


class MockName:
    """Mock Name object for serializer testing."""

    def __init__(self):
        self.id = uuid.uuid4()
        self.canonical_name = "Mateo"
        self.display_name = "Mateo"
        self.gender_usage = ["boy"]
        self.origin_backgrounds = ["Spanish", "Italian"]
        self.languages = ["es", "it", "en"]
        self.length_category = "medium"
        self.age_style_category = "modern"
        self.historical_significance_score = 0.65
        self.semantic_summary = "A modern name of Spanish and Italian origin."


class MockDeckItem:
    """Mock RecommendationDeckItem for serializer testing."""

    def __init__(self, name: MockName):
        self.id = uuid.uuid4()
        self.name_id = name.id
        self.name = name
        self.rank = 1
        self.retrieval_score = 0.92
        self.rerank_score = 0.88
        self.explanation_summary = "Strong cultural match with Spanish heritage preference."


@pytest.fixture
def mock_name():
    return MockName()


@pytest.fixture
def mock_deck_item(mock_name):
    return MockDeckItem(mock_name)


class TestDeckItemSerializerOutput:
    """Tests for DeckItemSerializer nested name output."""

    def test_serializer_contains_nested_name_key(self, mock_deck_item):
        """DeckItemSerializer output contains a 'name' key with nested name data."""
        serializer = DeckItemSerializer(mock_deck_item)
        data = serializer.data

        assert "name" in data
        assert isinstance(data["name"], dict)

    def test_nested_name_contains_all_expected_fields(self, mock_deck_item):
        """The nested name object contains all fields from MatchNameSerializer."""
        serializer = DeckItemSerializer(mock_deck_item)
        name_data = serializer.data["name"]

        expected_fields = {
            "id",
            "canonical_name",
            "display_name",
            "gender_usage",
            "origin_backgrounds",
            "languages",
            "length_category",
            "age_style_category",
            "historical_significance_score",
            "semantic_summary",
        }
        assert set(name_data.keys()) == expected_fields

    def test_nested_name_values_match_source(self, mock_deck_item, mock_name):
        """The nested name field values match the related Name object."""
        serializer = DeckItemSerializer(mock_deck_item)
        name_data = serializer.data["name"]

        assert name_data["canonical_name"] == mock_name.canonical_name
        assert name_data["display_name"] == mock_name.display_name
        assert name_data["origin_backgrounds"] == mock_name.origin_backgrounds
        assert name_data["gender_usage"] == mock_name.gender_usage
        assert name_data["length_category"] == mock_name.length_category
        assert name_data["age_style_category"] == mock_name.age_style_category
        assert name_data["historical_significance_score"] == mock_name.historical_significance_score
        assert name_data["languages"] == mock_name.languages
        assert str(name_data["id"]) == str(mock_name.id)

    def test_top_level_fields_present(self, mock_deck_item):
        """DeckItemSerializer output contains all expected top-level fields."""
        serializer = DeckItemSerializer(mock_deck_item)
        data = serializer.data

        expected_top_level = {"id", "name_id", "name", "rank", "retrieval_score", "rerank_score", "explanation_summary"}
        assert set(data.keys()) == expected_top_level

    def test_top_level_values_correct(self, mock_deck_item, mock_name):
        """Top-level field values are correct."""
        serializer = DeckItemSerializer(mock_deck_item)
        data = serializer.data

        assert str(data["id"]) == str(mock_deck_item.id)
        assert str(data["name_id"]) == str(mock_name.id)
        assert data["rank"] == 1
        assert data["retrieval_score"] == pytest.approx(0.92)
        assert data["rerank_score"] == pytest.approx(0.88)
        assert data["explanation_summary"] == "Strong cultural match with Spanish heritage preference."
