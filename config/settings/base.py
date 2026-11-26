import os
from pathlib import Path

import dj_database_url

from config.loader import load_config

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "").split(",") if h]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "apps.core",
    "apps.agenda",
    "apps.assistant",
    "apps.channel",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": dj_database_url.config(
        default="postgres:///lexagenda_c1", conn_max_age=600
    )
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
]

LANGUAGE_CODE = "es-mx"
TIME_ZONE = "America/Mexico_City"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "/login/"

# Read once at boot; a broken file must stop the container, not fail silently.
CONFIG = load_config(os.environ.get("LEXAGENDA_CONFIG", BASE_DIR / "config.yaml"))

# The lawyer's WhatsApp identity and the webhook secret (secrets stay in env).
LAWYER_JID = os.environ.get("LAWYER_JID", "")
ASSISTANT_NUMBER = os.environ.get("ASSISTANT_NUMBER", "")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

# The account the dashboard belongs to; the ops console resets its 2FA (PLAN §11).
LAWYER_USERNAME = os.environ.get("LAWYER_USERNAME", "abogado")

# The 2FA reset emails the lawyer; an unimplemented relay fails loudly in the reset view.
EMAIL_HOST = os.environ.get("EMAIL_HOST", "localhost")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "0") == "1"
DEFAULT_FROM_EMAIL = os.environ.get("EMAIL_FROM", "lexagenda@localhost")

GOWA_URL = os.environ.get("GOWA_URL", "http://gowa:3000")
GOWA_BASIC_AUTH = os.environ.get("GOWA_BASIC_AUTH", "")
GOWA_DEVICE_A = os.environ.get("GOWA_DEVICE_A", "")

# Routes API: one traffic-aware call per leg, cached and capped (PLAN §8.2, §16).
ROUTES_URL = os.environ.get("ROUTES_URL", "https://routes.googleapis.com")
ROUTES_API_KEY = os.environ.get("ROUTES_API_KEY", "")
ROUTES_DAILY_CAP = int(os.environ.get("ROUTES_DAILY_CAP", "500"))
ROUTES_TIMEOUT = 10

LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "")
LLM_MODEL = os.environ.get("LLM_MODEL", "")
LLM_FALLBACK_MODEL = os.environ.get("LLM_FALLBACK_MODEL", "")
LLM_REFERER = os.environ.get("LLM_REFERER", "")
LLM_TITLE = os.environ.get("LLM_TITLE", "lexagenda")
