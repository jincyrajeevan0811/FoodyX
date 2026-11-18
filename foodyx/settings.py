"""FoodyX - Restaurant Management System settings."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get(
    "FOODYX_SECRET_KEY",
    "dev-only-change-me-7f3c1e9b2a4d4b6c8e0f1a2b3c4d5e6f",
)
# Vercel sets VERCEL=1 in its build and runtime environment.
ON_VERCEL = bool(os.environ.get("VERCEL"))

DEBUG = os.environ.get("FOODYX_DEBUG", "0" if ON_VERCEL else "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("FOODYX_ALLOWED_HOSTS", "*").split(",") if h]
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("FOODYX_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]
if ON_VERCEL:
    CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")
    # Vercel terminates HTTPS in front of the app.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "core",
    "saas",
    "restaurant",
    "storefront",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.setup_check.SetupCheckMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.middleware.SingleDeviceMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "foodyx.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.context_processors.foodyx",
            ],
        },
    },
]

WSGI_APPLICATION = "foodyx.wsgi.application"

# Local development uses SQLite. In production (Vercel) set DATABASE_URL to a
# PostgreSQL database, e.g. Neon or Vercel Postgres — serverless functions
# cannot keep a SQLite file.
def _find_database_url():
    """DATABASE_URL, or whatever name Vercel's Neon integration used.

    The integration names variables after the "Custom prefix" chosen when it
    was connected (DATABASE_URL, STORAGE_URL, FOODYX_URL, …), so fall back to
    any *_URL variable that holds a Postgres address (pooled one preferred).
    """
    for name in ("DATABASE_URL", "POSTGRES_URL", "STORAGE_URL"):
        if os.environ.get(name):
            return os.environ[name]
    found = sorted(
        (("UNPOOLED" in k.upper(), k), v) for k, v in os.environ.items()
        if k.upper().endswith(("_URL", "_URL_UNPOOLED")) and v.startswith(("postgres://", "postgresql://"))
    )
    return found[0][1] if found else None


DATABASE_URL = _find_database_url()
if DATABASE_URL:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=0, conn_health_checks=True)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_USER_MODEL = "core.User"
AUTHENTICATION_BACKENDS = ["core.backends.PhoneEmailUsernameBackend"]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 6}},
]

LOGIN_URL = "core:login"
LOGIN_REDIRECT_URL = "core:home_redirect"
LOGOUT_REDIRECT_URL = "core:landing"

LANGUAGE_CODE = "en-in"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
# WhiteNoise serves /static/ in production straight from the app folders,
# so no separate collectstatic step is needed on Vercel.
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MESSAGE_TAGS = {40: "error"}

# Email falls back to the console in development; SMTP values saved in
# Platform settings take over automatically once configured.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "FoodyX <no-reply@foodyx.app>"


# Print errors (with tracebacks) to the console so they show up in
# `runserver` output and in Vercel → Deployments → Logs.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "foodyx.setup": {"handlers": ["console"], "level": "ERROR", "propagate": False},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}
