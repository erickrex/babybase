"""Core models for BabyBase."""

import uuid

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.db.models import Q


class BaseModel(models.Model):
    """Abstract base model with UUID primary key and timestamps."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class CoupleStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    ACTIVE = "active", "Active"
    ARCHIVED = "archived", "Archived"


class NameAge(models.TextChoices):
    NEW = "new", "New"
    OLD = "old", "Old"
    BALANCED = "balanced", "Balanced"


class BabyGender(models.TextChoices):
    BOY = "boy", "Boy"
    GIRL = "girl", "Girl"
    NON_BINARY = "non_binary", "Non-binary"


class NameLength(models.TextChoices):
    SHORT = "short", "Short"
    LONG = "long", "Long"
    ANY = "any", "Any"


class HistoricalImportance(models.TextChoices):
    LOW = "low", "Low"
    MEDIUM = "medium", "Medium"
    HIGH = "high", "High"


class UserManager(BaseUserManager):
    """Custom user manager that uses email as the unique identifier."""

    def create_user(self, email: str, password: str | None = None, **extra_fields):
        if not email:
            raise ValueError("The Email field must be set")
        email = self.normalize_email(email)
        extra_fields.setdefault("is_active", True)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user model with email as the login field and UUID primary key."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=150, blank=True)
    role_in_pregnancy = models.CharField(
        max_length=10,
        choices=[("father", "Father"), ("mother", "Mother")],
        blank=True,
    )
    age = models.IntegerField(null=True, blank=True)
    gender = models.CharField(max_length=50, null=True, blank=True)
    nationality = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Use email as the login field instead of username
    username = None
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        db_table = "core_user"

    def __str__(self) -> str:
        return self.email


class Couple(BaseModel):
    """Represents a couple (two partners) in the system."""

    user_a = models.ForeignKey(User, on_delete=models.CASCADE, related_name="couples_as_a")
    user_b = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="couples_as_b", null=True, blank=True
    )
    status = models.CharField(
        max_length=10,
        choices=CoupleStatus.choices,
        default=CoupleStatus.PENDING,
    )
    invite_email = models.EmailField(null=True, blank=True)
    residence_country = models.CharField(max_length=2, null=True, blank=True)

    class Meta:
        db_table = "core_couple"
        constraints = [
            models.UniqueConstraint(
                fields=["user_a", "user_b"],
                name="unique_couple_pair",
            ),
            models.CheckConstraint(
                condition=~models.Q(user_a=models.F("user_b")),
                name="couple_users_must_differ",
            ),
            models.UniqueConstraint(
                fields=["user_a"],
                condition=Q(status=CoupleStatus.ACTIVE),
                name="unique_active_couple_for_user_a",
            ),
            models.UniqueConstraint(
                fields=["user_b"],
                condition=Q(status=CoupleStatus.ACTIVE, user_b__isnull=False),
                name="unique_active_couple_for_user_b",
            ),
            models.UniqueConstraint(
                fields=["user_a"],
                condition=Q(status=CoupleStatus.PENDING),
                name="unique_pending_invite_per_user_a",
            ),
        ]
        indexes = [
            models.Index(fields=["status"], name="idx_couple_status"),
        ]

    def __str__(self) -> str:
        partner = self.user_b.email if self.user_b else self.invite_email
        return f"Couple({self.user_a.email} + {partner})"


class OnboardingResponse(BaseModel):
    """Stores a user's onboarding preference answers for their couple."""

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="onboarding_responses")
    couple = models.ForeignKey(
        Couple, on_delete=models.CASCADE, related_name="onboarding_responses",
        null=True, blank=True,
    )
    preferred_name_backgrounds = models.JSONField(default=list)
    preferred_name_age = models.CharField(
        max_length=10,
        choices=NameAge.choices,
    )
    baby_gender_preference = models.CharField(
        max_length=10,
        choices=BabyGender.choices,
    )
    preferred_name_length = models.CharField(
        max_length=10,
        choices=NameLength.choices,
    )
    historical_importance = models.CharField(
        max_length=10,
        choices=HistoricalImportance.choices,
    )

    class Meta:
        db_table = "core_onboarding_response"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "couple"],
                condition=Q(couple__isnull=False),
                name="unique_onboarding_response_per_user_couple",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(couple__isnull=True),
                name="unique_solo_onboarding_response_per_user",
            ),
        ]

    def __str__(self) -> str:
        return f"OnboardingResponse({self.user.email})"


class SwipeAction(models.TextChoices):
    LIKE = "like", "Like"
    DISLIKE = "dislike", "Dislike"
    MAYBE = "maybe", "Maybe"


class DeckMode(models.TextChoices):
    BEST_MATCH = "best_match", "Best Match"
    BRIDGE_NAMES = "bridge_names", "Bridge Names"
    MORE_LIKE_THIS = "more_like_this", "More Like This"
    WILDCARD = "wildcard", "Wildcard"
    CROSS_CULTURAL = "cross_cultural", "Names That Travel"
    SOUNDS_LIKE = "sounds_like", "Sounds Like"


class LengthCategory(models.TextChoices):
    SHORT = "short", "Short"
    MEDIUM = "medium", "Medium"
    LONG = "long", "Long"


class AgeStyleCategory(models.TextChoices):
    CLASSIC = "classic", "Classic"
    MODERN = "modern", "Modern"
    TIMELESS = "timeless", "Timeless"


class Name(BaseModel):
    """Canonical baby name with full metadata for semantic search and recommendations."""

    canonical_name = models.CharField(max_length=100, unique=True)
    display_name = models.CharField(max_length=100)
    gender_usage = models.JSONField(default=list)  # ['boy'], ['girl'], ['boy', 'girl']
    origin_backgrounds = models.JSONField(default=list)  # ['Spanish', 'Greek', 'Russian']
    languages = models.JSONField(default=list)  # ['es', 'en', 'ru']
    scripts = models.JSONField(default=list)  # ['Latin', 'Cyrillic']
    variants = models.JSONField(default=list)  # ['Sofia', 'Sofía', 'Sofiya']
    length_category = models.CharField(
        max_length=10,
        choices=LengthCategory.choices,
    )
    age_style_category = models.CharField(
        max_length=10,
        choices=AgeStyleCategory.choices,
    )
    historical_significance_score = models.FloatField(default=0.0)
    semantic_summary = models.TextField()
    active = models.BooleanField(default=True)
    x_2d = models.FloatField(null=True, blank=True, help_text="Precomputed 2D projection x-coordinate")
    y_2d = models.FloatField(null=True, blank=True, help_text="Precomputed 2D projection y-coordinate")
    phonetic_profile = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Cached Nova phonetic profile describing how the name sounds. "
            "Empty dict means not yet enriched. Shape: "
            '{"ipa": "ˈeɪdən", "rhyme": "-aden", "syllables": 2, '
            '"stress": "primary on first syllable", '
            '"sounds_like": "rhymes with Braden and Jayden; two beats, soft ending", '
            '"model": "amazon.nova-lite-v1:0", "generated_at": "2026-06-01T12:00:00Z"}'
        ),
    )
    pronunciation_audio = models.JSONField(
        default=dict,
        blank=True,
        help_text=(
            "Reference to the Polly-generated pronunciation audio stored in S3. "
            "Empty dict means no audio has been generated. Shape: "
            '{"bucket": "babybase-pronunciation-audio-...", '
            '"key": "pronunciations/<name_id>.mp3", "voice": "Joanna", '
            '"content_type": "audio/mpeg", "generated_at": "2026-06-01T12:00:00Z"}'
        ),
    )

    class Meta:
        db_table = "core_name"
        constraints = [
            models.UniqueConstraint(
                fields=["canonical_name"],
                name="unique_canonical_name",
            ),
        ]
        indexes = [
            models.Index(fields=["active"], name="idx_name_active"),
            models.Index(fields=["canonical_name"], name="idx_name_canonical"),
        ]

    def __str__(self) -> str:
        return self.display_name


class NameVectorIndexRef(BaseModel):
    """Links a Name record to its Qdrant vector point."""

    name = models.OneToOneField(Name, on_delete=models.CASCADE, related_name="vector_ref")
    qdrant_collection = models.CharField(max_length=100, default="names_global_v1")
    qdrant_point_id = models.UUIDField()
    embedding_version = models.CharField(max_length=20)
    indexed_at = models.DateTimeField()

    class Meta:
        db_table = "core_name_vector_index_ref"

    def __str__(self) -> str:
        return f"VectorRef({self.name.canonical_name} @ {self.qdrant_collection})"



class RecommendationDeck(BaseModel):
    """A generated deck of name recommendations for a couple."""

    couple = models.ForeignKey(Couple, on_delete=models.CASCADE, related_name="decks")
    mode = models.CharField(
        max_length=20,
        choices=DeckMode.choices,
        default=DeckMode.BEST_MATCH,
    )
    retrieval_profile_json = models.JSONField(default=dict)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_recommendation_deck"
        indexes = [
            models.Index(fields=["couple", "-created_at"], name="idx_deck_couple_created"),
        ]

    def __str__(self) -> str:
        return f"Deck({self.couple}, mode={self.mode})"


class RecommendationDeckItem(BaseModel):
    """A single name item within a recommendation deck."""

    deck = models.ForeignKey(RecommendationDeck, on_delete=models.CASCADE, related_name="items")
    name = models.ForeignKey(Name, on_delete=models.CASCADE, related_name="deck_appearances")
    rank = models.IntegerField()
    retrieval_score = models.FloatField(default=0.0)
    rerank_score = models.FloatField(default=0.0)
    explanation_summary = models.TextField(blank=True, default="")

    class Meta:
        db_table = "core_recommendation_deck_item"
        ordering = ["rank"]
        indexes = [
            models.Index(fields=["deck", "rank"], name="idx_deck_item_rank"),
        ]

    def __str__(self) -> str:
        return f"DeckItem({self.name.canonical_name}, rank={self.rank})"


class MatchStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    SHORTLISTED = "shortlisted", "Shortlisted"
    DISMISSED = "dismissed", "Dismissed"


class Swipe(BaseModel):
    """Records a single user's swipe action on a name within their couple."""

    couple = models.ForeignKey(Couple, on_delete=models.CASCADE, related_name="swipes")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="swipes")
    name = models.ForeignKey(Name, on_delete=models.CASCADE, related_name="swipes")
    action = models.CharField(
        max_length=10,
        choices=SwipeAction.choices,
    )
    source_deck = models.ForeignKey(
        RecommendationDeck,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="swipes",
    )

    class Meta:
        db_table = "core_swipe"
        constraints = [
            models.UniqueConstraint(
                fields=["couple", "user", "name"],
                name="unique_swipe_per_user_name_couple",
            ),
        ]
        indexes = [
            models.Index(fields=["couple", "name"], name="idx_swipe_couple_name"),
            models.Index(fields=["couple", "user", "name"], name="idx_swipe_couple_user_name"),
        ]

    def __str__(self) -> str:
        return f"Swipe({self.user.email} → {self.name.canonical_name}: {self.action})"


class MutualMatch(BaseModel):
    """A mutual match — both parents liked the same name."""

    couple = models.ForeignKey(Couple, on_delete=models.CASCADE, related_name="matches")
    name = models.ForeignKey(Name, on_delete=models.CASCADE, related_name="matches")
    matched_at = models.DateTimeField(auto_now_add=True)
    match_strength_score = models.FloatField(default=0.0)
    status = models.CharField(
        max_length=15,
        choices=MatchStatus.choices,
        default=MatchStatus.ACTIVE,
    )
    # When set, one partner has requested to remove this shortlisted name and
    # is waiting for the other partner to approve. Cleared on approve/cancel/reject.
    removal_requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="requested_match_removals",
    )

    class Meta:
        db_table = "core_mutual_match"
        constraints = [
            models.UniqueConstraint(
                fields=["couple", "name"],
                name="unique_match_per_couple_name",
            ),
        ]
        indexes = [
            models.Index(fields=["couple", "status"], name="idx_match_couple_status"),
        ]

    def __str__(self) -> str:
        return f"Match({self.couple} ↔ {self.name.canonical_name})"


class UserTasteVector(BaseModel):
    """Per-user taste vector with quality metrics for Phase D eligibility."""

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="taste_vector")
    embedding = models.JSONField(default=list)  # list[float], 1024 dimensions
    swipe_count = models.IntegerField(default=0)
    like_rate = models.FloatField(default=0.0)  # likes / total_swipes
    vector_variance = models.FloatField(default=0.0)  # avg squared distance to centroid
    confidence_score = models.FloatField(default=0.0)  # composite [0.0, 1.0]
    last_updated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "core_user_taste_vector"
        indexes = [
            models.Index(fields=["confidence_score"], name="idx_taste_vector_confidence"),
            models.Index(fields=["last_updated_at"], name="idx_taste_vector_updated"),
        ]

    def __str__(self):
        return f"TasteVector({self.user.email}, confidence={self.confidence_score:.2f})"
