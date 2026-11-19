"""Prepare the database automatically on Vercel.

Runs once per cold start (from foodyx/wsgi.py, only when VERCEL is set) and
again from the setup page if tables are still missing:

1. If the repository has no migration files, generate them in /tmp.
2. Apply migrations (creates the tables on a new database; quick no-op later).
3. On a completely empty database, load the demo data (plans, super admin,
   demo restaurant) unless FOODYX_SEED_DEMO=0.

Failures are logged (Vercel → Logs) and remembered in LAST_ERROR so the
setup page can show the reason. They never stop the site from starting.
"""
import importlib
import logging
import os
import traceback

logger = logging.getLogger("foodyx.boot")

LAST_ERROR = ""


def _remember(step, exc):
    global LAST_ERROR
    LAST_ERROR = f"{step}: {exc.__class__.__name__}: {str(exc).strip().splitlines()[0][:300] if str(exc).strip() else ''}"
    logger.error("Automatic %s failed\n%s", step, traceback.format_exc())


def prepare_database():
    """Returns True when the tables are in place."""
    global LAST_ERROR
    from django.conf import settings
    from django.core.management import call_command

    if not getattr(settings, "DATABASE_URL", None):
        logger.warning("No Postgres connection string found; skipping database preparation.")
        return False

    temp_apps = getattr(settings, "FX_TEMP_MIGRATIONS", [])
    try:
        if temp_apps:
            logger.info("Generating migrations in /tmp for %s", ", ".join(temp_apps))
            call_command("makemigrations", *temp_apps, interactive=False, verbosity=0)
            # The files were written a moment ago; make Python's import system
            # look at the folders again instead of using its cached listing.
            importlib.invalidate_caches()
    except Exception as exc:
        _remember("makemigrations", exc)
        return False
    try:
        call_command("migrate", interactive=False, verbosity=0)
    except Exception as exc:
        _remember("migrate", exc)
        return False

    LAST_ERROR = ""
    if os.environ.get("FOODYX_SEED_DEMO", "1") == "1":
        try:
            from django.contrib.auth import get_user_model

            if not get_user_model().objects.exists():
                logger.info("Empty database: loading demo data")
                # A short history keeps the first start well inside Vercel's time limit.
                call_command("seed_demo", days=2)
        except Exception as exc:
            # Another instance may be seeding at the same moment; that is fine.
            _remember("demo data", exc)
    return True
