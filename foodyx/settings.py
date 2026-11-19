"""FoodyX - Restaurant Management System settings.

Local development: SQLite, DEBUG on — nothing to configure.
Vercel (free Hobby plan): detected automatically through the VERCEL
environment variable; needs a Postgres database (Neon) in DATABASE_URL.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Vercel sets VERCEL=1 during builds and at runtime.
ON_VERCEL = bool(os.environ.get("VERCEL"))

SECRET_KEY = os.environ.get(
    "FOODYX_SECRET_KEY",
    "dev-only-change-me-7f3c1e9b2a4d4b6c8e0f1a2b3c4d5e6f",
)
DEBUG = os.environ.get("FOODYX_DEBUG", "0" if ON_VERCEL else "1") == "1"
ALLOWED_HOSTS = [h for h in os.environ.get("FOODYX_ALLOWED_HOSTS", "*").split(",") if h]
CSRF_TRUSTED_ORIGINS = [
    o for o in os.environ.get("FOODYX_CSRF_TRUSTED_ORIGINS", "").split(",") if o
]
if ON_VERCEL:
    CSRF_TRUSTED_ORIGINS.append("https://*.vercel.app")
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")  # HTTPS ends at Vercel's edge
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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "core.setup_check.SetupCheckMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "core.middleware.SingleDeviceMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# WhiteNoise serves static files on Vercel. Locally it is optional, so the
# project still runs even before `pip install -r requirements.txt`.
try:
    import whitenoise  # noqa: F401

    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")
except ImportError:
    if ON_VERCEL:
        raise

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

def _find_database_url():
    """DATABASE_URL, or whatever name Vercel's Neon integration created.

    The integration prefixes its variables with the "Custom prefix" chosen
    when connecting (DATABASE_URL, STORAGE_URL, FOODYX_URL …), so any *_URL
    variable holding a postgres:// address is accepted (pooled preferred).
    """
    for name in ("DATABASE_URL", "POSTGRES_URL", "STORAGE_URL"):
        if os.environ.get(name):
            return os.environ[name]
    found = sorted(
        (("UNPOOLED" in k.upper(), k), v) for k, v in os.environ.items()
        if k.upper().endswith(("_URL", "_URL_UNPOOLED")) and v.startswith(("postgres://", "postgresql://"))
    )
    return found[0][1] if found else None


# Only read on Vercel, so a variable left over in a local terminal can never
# switch your local copy to the online database by accident.
DATABASE_URL = _find_database_url() if ON_VERCEL or os.environ.get("FOODYX_USE_DATABASE_URL") == "1" else None
if DATABASE_URL:
    import dj_database_url

    DATABASES = {"default": dj_database_url.parse(DATABASE_URL, conn_max_age=0, conn_health_checks=True)}
    # Neon's pooled address runs PgBouncer in transaction mode.
    DATABASES["default"]["DISABLE_SERVER_SIDE_CURSORS"] = True
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

# Migration files are normally generated locally and committed. If they are
# missing from the repository, Vercel generates them at start-up in /tmp
# (the only writable folder) so the tables can still be created.
FOODYX_APPS = ("core", "saas", "restaurant")
FX_TEMP_MIGRATIONS = []
if ON_VERCEL:
    _missing = [a for a in FOODYX_APPS if not any((BASE_DIR / a / "migrations").glob("0*.py"))]
    if _missing:
        _tmp = Path("/tmp/fx_migrations")
        for _app in _missing:
            (_tmp / _app).mkdir(parents=True, exist_ok=True)
            (_tmp / _app / "__init__.py").touch()
        (_tmp / "__init__.py").touch()
        if "/tmp" not in sys.path:
            sys.path.insert(0, "/tmp")
        MIGRATION_MODULES = {a: f"fx_migrations.{a}" for a in _missing}
        FX_TEMP_MIGRATIONS = _missing

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
# WhiteNoise serves /static/ straight from the app folders (no collectstatic needed).
WHITENOISE_USE_FINDERS = True
WHITENOISE_AUTOREFRESH = DEBUG

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MESSAGE_TAGS = {40: "error"}

# Email falls back to the console in development; SMTP values saved in
# Platform settings take over automatically once configured.
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "FoodyX <no-reply@foodyx.app>"


# Errors (with tracebacks) go to the console: runserver output locally,
# Vercel → Deployments → Logs in production.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "ERROR", "propagate": False},
        "foodyx": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
    "root": {"handlers": ["console"], "level": "WARNING"},
}
