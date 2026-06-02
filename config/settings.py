"""
Django settings for BabyBase project.

Uses python-decouple for environment-based configuration.
"""

from pathlib import Path

from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

APP_ENV = config("APP_ENV", default="development").lower()
LOCAL_ENVIRONMENTS = {"development", "dev", "local", "test"}
IS_LOCAL_ENV = APP_ENV in LOCAL_ENVIRONMENTS

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config(
    "SECRET_KEY",
    default="django-insecure-dev-key-change-in-production" if IS_LOCAL_ENV else "",
)
if not SECRET_KEY:
    raise ImproperlyConfigured("SECRET_KEY must be set outside local development.")

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config("DEBUG", default=IS_LOCAL_ENV, cast=bool)
if not IS_LOCAL_ENV and DEBUG:
    raise ImproperlyConfigured("DEBUG must be False outside local development.")

ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third-party
    "rest_framework",
    "rest_framework.authtoken",
    "corsheaders",
    # Local
    "core",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "core.middleware.RequestLoggingMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Database
# https://docs.djangoproject.com/en/5.2/ref/settings/#databases
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME", default="babybase"),
        "USER": config("DB_USER", default="postgres"),
        "PASSWORD": config("DB_PASSWORD", default="postgres"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
        "CONN_MAX_AGE": config("CONN_MAX_AGE", default=600, cast=int),
        "CONN_HEALTH_CHECKS": config("CONN_HEALTH_CHECKS", default=True, cast=bool),
    }
}

# Custom user model
AUTH_USER_MODEL = "core.User"

# Password validation
# Disabled in dev — accept any password (we are still developing)
AUTH_PASSWORD_VALIDATORS = []

# Password hashers — Argon2 as primary
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]

# Internationalization
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Default primary key field type
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Django REST Framework
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_THROTTLE_CLASSES": [
        "core.throttles.GeneralAPIRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "login": "5/15min",
        "general": "1000/hour",
        "swipe": "200/hour",
    },
}

# CORS Configuration
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:5173,http://127.0.0.1:5173",
    cast=Csv(),
)
CORS_ALLOW_CREDENTIALS = True

# Qdrant Configuration
QDRANT_URL = config("QDRANT_URL", default="")
QDRANT_API_KEY = config("QDRANT_API_KEY", default="")
QDRANT_COLLECTION = config("QDRANT_COLLECTION", default="names_global_v1")
QDRANT_TIMEOUT_SECONDS = config("QDRANT_TIMEOUT_SECONDS", default=180, cast=int)

# AWS Bedrock Configuration
AWS_BEDROCK_REGION = config("AWS_BEDROCK_REGION", default="us-east-1")
# Bounded timeouts for synchronous Bedrock embedding calls on the deck path.
# Keep these well under the frontend's 30s request deadline so a stalled call
# fails fast (and retries) instead of blocking deck generation.
BEDROCK_CONNECT_TIMEOUT_SECONDS = config("BEDROCK_CONNECT_TIMEOUT_SECONDS", default=5, cast=int)
BEDROCK_READ_TIMEOUT_SECONDS = config("BEDROCK_READ_TIMEOUT_SECONDS", default=8, cast=int)

# Phonetic "Sounds Like" Configuration
# Amazon Bedrock Nova model used to generate cached phonetic profiles
NOVA_MODEL_ID = config("NOVA_MODEL_ID", default="amazon.nova-lite-v1:0")
# S3 bucket for storing Amazon Polly pronunciation audio
PRONUNCIATION_AUDIO_BUCKET = config("PRONUNCIATION_AUDIO_BUCKET", default="")
# Amazon Polly neural voice used to synthesize pronunciation audio
PRONUNCIATION_VOICE = config("PRONUNCIATION_VOICE", default="Joanna")
# Time-to-live (seconds) for presigned pronunciation audio URLs
PRONUNCIATION_URL_TTL_SECONDS = config("PRONUNCIATION_URL_TTL_SECONDS", default=3600, cast=int)

# Logging Configuration
LOG_LEVEL = config("LOG_LEVEL", default="INFO")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "simple": {
            "format": "{levelname} {name}: {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "WARNING",
    },
    "loggers": {
        "core": {
            "level": LOG_LEVEL,
            "propagate": True,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": config("DB_LOG_LEVEL", default="WARNING"),
            "propagate": False,
        },
    },
}
