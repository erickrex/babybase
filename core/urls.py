"""URL configuration for the core app."""

from django.urls import path

from core.views.auth import health_check_view, login_view, logout_view, register_view
from core.views.constellation import constellation_view
from core.views.couples import couple_invite_view, couple_me_view
from core.views.onboarding import onboarding_preferences_view
from core.views.profiles import profile_me_view
from core.views.recommendations import generate_deck_view, get_deck_view
from core.views.swipes import (
    match_detail_view,
    matches_list_view,
    shortlist_view,
    similar_names_view,
    swipe_view,
)

urlpatterns = [
    # Auth
    path("auth/register/", register_view, name="auth-register"),
    path("auth/login/", login_view, name="auth-login"),
    path("auth/logout/", logout_view, name="auth-logout"),
    # Profile
    path("profile/me/", profile_me_view, name="profile-me"),
    # Couples
    path("couples/invite/", couple_invite_view, name="couple-invite"),
    path("couples/me/", couple_me_view, name="couple-me"),
    # Onboarding
    path("onboarding/preferences/", onboarding_preferences_view, name="onboarding-preferences"),
    # Recommendations
    path("recommendations/deck/", generate_deck_view, name="recommendations-generate-deck"),
    path("recommendations/deck/<str:deck_id>/", get_deck_view, name="recommendations-get-deck"),
    # Swipes
    path("swipes/", swipe_view, name="swipes-create"),
    # Matches
    path("matches/", matches_list_view, name="matches-list"),
    path("matches/<str:name_id>/", match_detail_view, name="matches-detail"),
    path("matches/<str:name_id>/similar/", similar_names_view, name="matches-similar"),
    # Shortlist
    path("shortlist/", shortlist_view, name="shortlist"),
    # Constellation
    path("constellation/", constellation_view, name="constellation"),
    # Health
    path("health/", health_check_view, name="health-check"),
]
