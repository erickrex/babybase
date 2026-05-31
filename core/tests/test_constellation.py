"""API tests for the insights-first name map endpoint."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from core.models import (
    Couple,
    CoupleStatus,
    MatchStatus,
    MutualMatch,
    Name,
    OnboardingResponse,
    RecommendationDeck,
    RecommendationDeckItem,
    Swipe,
    SwipeAction,
)

User = get_user_model()


def api_client_for(user) -> APIClient:
    token, _ = Token.objects.get_or_create(user=user)
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    return client


def make_name(
    canonical: str,
    *,
    display: str | None = None,
    origins: list[str] | None = None,
    gender: list[str] | None = None,
    style: str = "classic",
    length: str = "short",
    x: float | None = 0.5,
    y: float | None = 0.5,
    historical: float = 0.5,
) -> Name:
    return Name.objects.create(
        canonical_name=canonical,
        display_name=display or canonical,
        gender_usage=gender or ["girl"],
        origin_backgrounds=origins or ["English"],
        languages=["en"],
        scripts=["Latin"],
        variants=[],
        length_category=length,
        age_style_category=style,
        historical_significance_score=historical,
        semantic_summary=f"{canonical} test name.",
        active=True,
        x_2d=x,
        y_2d=y,
    )


def onboard(user, couple, backgrounds: list[str]) -> OnboardingResponse:
    return OnboardingResponse.objects.create(
        user=user,
        couple=couple,
        preferred_name_backgrounds=backgrounds,
        preferred_name_age="balanced",
        baby_gender_preference="girl",
        preferred_name_length="any",
        historical_importance="medium",
    )


@pytest.mark.django_db
class TestConstellationView:
    def test_returns_insight_payload_for_couple(self):
        user_a = User.objects.create_user(email="map-a@test.com", password="testpass123")
        user_b = User.objects.create_user(email="map-b@test.com", password="testpass123")
        couple = Couple.objects.create(user_a=user_a, user_b=user_b, status=CoupleStatus.ACTIVE)
        onboard(user_a, couple, ["Spanish"])
        onboard(user_b, couple, ["German"])

        sofia = make_name("MapSofia", display="Sofia", origins=["Spanish"], x=0.2, y=0.2)
        alma = make_name("MapAlma", display="Alma", origins=["Spanish"], x=0.25, y=0.22)
        hugo = make_name(
            "MapHugo",
            display="Hugo",
            origins=["German"],
            gender=["boy"],
            style="modern",
            x=0.75,
            y=0.65,
        )
        nova = make_name("MapNova", display="Nova", origins=["Italian"], style="modern", x=0.55, y=0.45)

        MutualMatch.objects.create(
            couple=couple,
            name=sofia,
            match_strength_score=0.91,
            status=MatchStatus.SHORTLISTED,
        )
        Swipe.objects.create(couple=couple, user=user_a, name=sofia, action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_b, name=sofia, action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_a, name=alma, action=SwipeAction.LIKE)
        Swipe.objects.create(couple=couple, user=user_b, name=hugo, action=SwipeAction.LIKE)

        deck = RecommendationDeck.objects.create(couple=couple, mode="best_match")
        RecommendationDeckItem.objects.create(
            deck=deck,
            name=nova,
            rank=1,
            rerank_score=0.82,
            explanation_summary="Balances your current taste.",
        )

        response = api_client_for(user_a).get("/api/v1/constellation/")

        assert response.status_code == 200
        assert response.data["status"] == "success"
        data = response.data["data"]
        assert data["mode"] == "couple"
        assert data["summary"]["title"] == "Shared name taste"
        assert data["summary"]["stats"]["matched_count"] == 1
        assert data["summary"]["stats"]["shortlisted_count"] == 1

        statuses = {item["display_name"]: item["status"] for item in data["featured_names"]}
        assert statuses["Sofia"] == "shortlisted"
        assert statuses["Alma"] == "liked_by_you"
        assert statuses["Hugo"] == "liked_by_partner"
        assert statuses["Nova"] == "recommended"

        assert data["taste_neighborhoods"][0]["label"] == "Classic Spanish"
        assert data["taste_neighborhoods"][0]["count"] == 2
        assert data["parents"]["current_user"]["liked_count"] == 2
        assert data["parents"]["partner"]["liked_count"] == 2
        assert data["explore"]["bubbles"]
        assert "featured_name_ids" not in data["explore"]
        assert "names" not in data
        assert "clusters" not in data
        assert "matched_name_ids" not in data

    def test_solo_onboarded_user_gets_starter_map(self):
        user = User.objects.create_user(email="solo-map@test.com", password="testpass123")
        onboard(user, None, ["English"])
        make_name("SoloMapAva", display="Ava", origins=["English"], x=0.4, y=0.4)
        make_name("SoloMapMila", display="Mila", origins=["Spanish"], x=0.6, y=0.5)

        response = api_client_for(user).get("/api/v1/constellation/")

        assert response.status_code == 200
        data = response.data["data"]
        assert data["mode"] == "solo"
        assert data["summary"]["title"] == "Your name taste"
        assert data["parents"]["partner"] is None
        assert {item["status"] for item in data["featured_names"]} == {"starter"}

    def test_solo_user_without_onboarding_gets_clean_400(self):
        user = User.objects.create_user(email="new-map@test.com", password="testpass123")

        response = api_client_for(user).get("/api/v1/constellation/")

        assert response.status_code == 400
        assert response.data == {
            "status": "error",
            "message": "Complete onboarding before viewing your name map.",
        }
