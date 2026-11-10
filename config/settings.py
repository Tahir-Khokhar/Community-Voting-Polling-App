"""
Django settings for the Community Voting & Polling App.

This project demonstrates Django Templates + HTMX patterns:
  * HTMX live polling for vote counts
  * select_for_update() for race-free vote increments
  * Django signing framework for tamper-proof anonymous tokens
  * django-autoslug for slug auto-generation
  * Custom template tags for percentage bars
  * Content Security Policy middleware
"""

import os
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# --- Security -------------------------------------------------------------
# SECURITY WARNING: keep the secret key used in production secret!
# The dev fallback below is only used when SECRET_KEY is not set in the
# environment; never deploy with it. In production always set SECRET_KEY.
SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-ffn#q=45rh&tw%7e6wpwru)ac1&9gf3qlvs4_q3_wbl7!z$ahg",
)

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

# In production set DJANGO_ALLOWED_HOSTS to the real hostnames (comma-separated).
# Avoid "*" — it disables Django's Host header validation.
ALLOWED_HOSTS = os.environ.get(
    "DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1,0.0.0.0"
).split(",")

# Production-only transport security. These only take effect when DEBUG=False,
# so local dev over plain HTTP keeps working, while a deploy with DJANGO_DEBUG=False
# automatically gets HSTS, HTTPS redirect and Secure cookies.
if not DEBUG:
    SECURE_SSL_REDIRECT = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


# --- Applications ---------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Third party
    "autoslug",
    # Local
    "polls",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # Local: Content Security Policy header injection
    "polls.middleware.ContentSecurityPolicyMiddleware",
]

ROOT_URLCONF = "config.urls"

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
                "polls.context_processors.poll_settings",
                "polls.context_processors.csp_nonce",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# --- Database -------------------------------------------------------------
# SQLite for local dev (zero config). For production set the DJANGO_DB_*
# variables to point at PostgreSQL (psycopg required):
#   DJANGO_DB_ENGINE=django.db.backends.postgresql
#   DJANGO_DB_NAME=polls  DJANGO_DB_USER=polls  DJANGO_DB_PASSWORD=...
#   DJANGO_DB_HOST=...  DJANGO_DB_PORT=5432
# PostgreSQL is the only production backend whose migrations, partial unique
# constraints, and select_for_update() row locks have been designed for (MySQL
# is NOT verified — see README).
if os.environ.get("DJANGO_DB_ENGINE"):
    DATABASES = {
        "default": {
            "ENGINE": os.environ["DJANGO_DB_ENGINE"],
            "NAME": os.environ.get("DJANGO_DB_NAME", ""),
            "USER": os.environ.get("DJANGO_DB_USER", ""),
            "PASSWORD": os.environ.get("DJANGO_DB_PASSWORD", ""),
            "HOST": os.environ.get("DJANGO_DB_HOST", ""),
            "PORT": os.environ.get("DJANGO_DB_PORT", ""),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }


# --- Email ----------------------------------------------------------------
# Used by django.contrib.auth's password-reset flow. Dev logs to the console;
# production should point DJANGO_EMAIL_BACKEND at SMTP via the variables below.
EMAIL_BACKEND = os.environ.get(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
EMAIL_HOST = os.environ.get("DJANGO_EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("DJANGO_EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("DJANGO_EMAIL_USE_TLS", "true").lower() in ("true", "1", "yes")
DEFAULT_FROM_EMAIL = os.environ.get("DJANGO_DEFAULT_FROM_EMAIL", "noreply@localhost")


# --- Cache ----------------------------------------------------------------
# Used by the vote-attempt throttle (see polls/throttling.py). In production
# set DJANGO_CACHE_BACKEND to a shared backend (memcached or Redis) and
# DJANGO_CACHE_LOCATION to its address, so the throttle counter is consistent
# across workers. LocMemCache (the default) is per-process and dev-only.
CACHES = {
    "default": {
        "BACKEND": os.environ.get(
            "DJANGO_CACHE_BACKEND",
            "django.core.cache.backends.locmem.LocMemCache",
        ),
        "LOCATION": os.environ.get("DJANGO_CACHE_LOCATION", "polls-throttle-v1"),
    }
}


# --- Password validation --------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# --- Internationalization -------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


# --- Static & media files -------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"


# --- Default primary key field --------------------------------------------
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# --- Auth redirects -------------------------------------------------------
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "polls:home"
LOGOUT_REDIRECT_URL = "polls:home"


# --- Clickjacking ---------------------------------------------------------
# Allow the widget view to be embedded in iframes. We override this per-view
# via the CSP middleware (frame-ancestors) for everything except the widget.
X_FRAME_OPTIONS = "DENY"


# --- Content Security Policy ----------------------------------------------
# A strict baseline CSP. The widget view relaxes frame-ancestors so the poll
# can be embedded on other sites; everything else denies being framed.
CSP_DEFAULT_SRC = ("'self'",)
CSP_SCRIPT_SRC = (
    "'self'",
    "https://cdn.tailwindcss.com",   # Tailwind CDN (dev convenience)
    "https://unpkg.com",             # HTMX
    "'unsafe-inline'",               # Tailwind CDN injects inline styles
)
CSP_STYLE_SRC = (
    "'self'",
    "https://cdn.tailwindcss.com",
    "https://fonts.googleapis.com",  # Google Fonts CSS stylesheet
    "'unsafe-inline'",               # Tailwind utility classes are inline
)
CSP_IMG_SRC = ("'self'", "data:", "https:")
CSP_FONT_SRC = ("'self'", "https://fonts.gstatic.com", "https://fonts.googleapis.com")
CSP_CONNECT_SRC = ("'self'",)
CSP_FRAME_ANCESTORS = ("'none'",)   # default: nobody may frame us
CSP_BASE_URI = ("'none'",)
CSP_FORM_ACTION = ("'self'",)


# --- Poll app settings ----------------------------------------------------
POLL_SETTINGS = {
    # Live-update polling interval for the HTMX results partial (seconds).
    "HTMX_POLL_INTERVAL_SECONDS": 3,
    # Token max age for anonymous voting signatures (seconds). 7 days.
    "ANON_TOKEN_MAX_AGE": 60 * 60 * 24 * 7,
    # Random ID length embedded in the anonymous token.
    "ANON_TOKEN_ID_LENGTH": 16,
    # Anonymous voter cookie lifetime (seconds). MUST be <= ANON_TOKEN_MAX_AGE
    # so the cookie expires no later than the signed token inside it. If the
    # cookie outlived the token, a visitor whose token had expired (but whose
    # cookie had not) would be minted a fresh token and could vote again
    # within the cookie's life — defeating one-vote-per-browser.
    "ANON_COOKIE_MAX_AGE": 60 * 60 * 24 * 7,
    # Lightweight vote-attempt throttle (per IP + poll). This is an abuse brake
    # only; the real one-vote-per-token guarantee comes from the signed token
    # plus the unique_ballot_per_token database constraint. Production should
    # configure a shared cache backend (memcached/Redis) so the counter is
    # consistent across workers; LocMemCache (the dev default) is per-process.
    "VOTE_THROTTLE_WINDOW_SECONDS": 60,
    "VOTE_THROTTLE_MAX_ATTEMPTS": 10,
}
