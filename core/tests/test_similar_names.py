"""Unit tests for the "More Like This" query path.

Covers ``core.services.swipes.get_similar_names``, which anchors on a name's
stored ``semantic`` vector in Qdrant and returns similar names, excluding the
anchor and the couple's already-swiped names — now constrained to the couple's
baby gender preference.

Qdrant and the Django ORM managers are mocked, so no real database or Qdrant
access is required. The real ``get_similar_to_names`` / ``search_names`` are
exercised end to end, so the filter and exclusion guarantees are genuinely
verified. This is the regression coverage for the bug where a boy-name match
surfaced girl names under "More Like This".
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings

from core.models import NameVectorIndexRef
from core.services.swipes import get_similar_names

ANCHOR_POINT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
VECTOR_DIM = 1024


class _Hit:
    """Minimal stand-in for a Qdrant query hit."""

    def __init__(self, point_id, score: float = 0.9):
        self.id = point_id
        self.score = score
        self.payload = {
            "name_id": str(point_id),
            "canonical_name": "Candidate",
            "origin_backgrounds": ["English"],
            "gender_usage": ["boy"],
            "length_category": "short",
            "age_style_category": "classic",
            "active": True,
        }


class _Point:
    """Minimal stand-in for a retrieved Qdrant point with named vectors."""

    def __init__(self, vector):
        self.vector = vector


def _anchor_point() -> _Point:
    return _Point({"semantic": [0.1] * VECTOR_DIM})


def _mock_client(retrieve_return, query_hits):
    client = MagicMock()
    client.retrieve.return_value = retrieve_return
    client.query_points.return_value.points = query_hits
    return client


def _configure_swipes(mock_swipe, swiped_point_ids):
    chain = mock_swipe.objects.filter.return_value.values_list.return_value
    chain.distinct.return_value = list(swiped_point_ids)


def _configure_index_ref(mock_nvir_objects, point_id=ANCHOR_POINT_ID):
    mock_nvir_objects.get.return_value = MagicMock(qdrant_point_id=point_id)


@pytest.fixture(autouse=True)
def _stub_couple_gender_profile():
    """Default to a mixed (non_binary) couple → no gender filter, DB-free."""
    with patch(
        "core.services.onboarding.build_couple_retrieval_profile",
        return_value={"baby_gender": "non_binary"},
    ):
        yield


@override_settings(QDRANT_COLLECTION="test_names")
@patch("core.services.onboarding.build_couple_retrieval_profile")
@patch("core.services.swipes.Swipe")
@patch("core.models.NameVectorIndexRef.objects")
@patch("core.services.qdrant_client.get_qdrant_client")
def test_similar_names_constrains_to_couple_gender(
    mock_get_client,
    mock_nvir_objects,
    mock_swipe,
    mock_profile,
):
    """The couple's baby gender is pushed to Qdrant as a gender_usage filter."""
    _configure_index_ref(mock_nvir_objects)
    _configure_swipes(mock_swipe, [])
    mock_profile.return_value = {"baby_gender": "boy"}

    mock_get_client.return_value = _mock_client([_anchor_point()], [_Hit(uuid.uuid4())])

    get_similar_names(str(uuid.uuid4()), MagicMock())

    query_filter = mock_get_client.return_value.query_points.call_args.kwargs["query_filter"]
    gender_conditions = [
        c for c in query_filter.must if getattr(c, "key", None) == "gender_usage"
    ]
    assert len(gender_conditions) == 1
    assert gender_conditions[0].match.value == "boy"


@override_settings(QDRANT_COLLECTION="test_names")
@patch("core.services.onboarding.build_couple_retrieval_profile")
@patch("core.services.swipes.Swipe")
@patch("core.models.NameVectorIndexRef.objects")
@patch("core.services.qdrant_client.get_qdrant_client")
def test_similar_names_no_gender_filter_when_non_binary(
    mock_get_client,
    mock_nvir_objects,
    mock_swipe,
    mock_profile,
):
    """A non_binary (mixed) preference applies no gender filter."""
    _configure_index_ref(mock_nvir_objects)
    _configure_swipes(mock_swipe, [])
    mock_profile.return_value = {"baby_gender": "non_binary"}

    mock_get_client.return_value = _mock_client([_anchor_point()], [_Hit(uuid.uuid4())])

    get_similar_names(str(uuid.uuid4()), MagicMock())

    query_filter = mock_get_client.return_value.query_points.call_args.kwargs["query_filter"]
    gender_conditions = [
        c for c in query_filter.must if getattr(c, "key", None) == "gender_usage"
    ]
    assert gender_conditions == []


@override_settings(QDRANT_COLLECTION="test_names")
@patch("core.services.swipes.Swipe")
@patch("core.models.NameVectorIndexRef.objects")
@patch("core.services.qdrant_client.get_qdrant_client")
def test_similar_names_excludes_anchor_and_swiped(
    mock_get_client, mock_nvir_objects, mock_swipe
):
    """The anchor and already-swiped names are filtered out of results."""
    _configure_index_ref(mock_nvir_objects)
    swiped = uuid.uuid4()
    _configure_swipes(mock_swipe, [swiped])

    survivor = uuid.uuid4()
    candidate_hits = [_Hit(survivor), _Hit(ANCHOR_POINT_ID), _Hit(swiped)]
    mock_get_client.return_value = _mock_client([_anchor_point()], candidate_hits)

    results = get_similar_names(str(uuid.uuid4()), MagicMock())

    returned = {r["point_id"] for r in results}
    assert str(ANCHOR_POINT_ID) not in returned
    assert str(swiped) not in returned
    assert returned == {str(survivor)}


@patch("core.services.qdrant_client.get_qdrant_client")
@patch("core.models.NameVectorIndexRef.objects")
def test_similar_names_empty_when_no_index_ref(mock_nvir_objects, mock_get_client):
    """A name with no stored vector yields an empty result and skips Qdrant."""
    mock_nvir_objects.get.side_effect = NameVectorIndexRef.DoesNotExist()

    results = get_similar_names(str(uuid.uuid4()), MagicMock())

    assert results == []
    mock_get_client.assert_not_called()
