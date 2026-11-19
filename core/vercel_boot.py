"""Prepare the database automatically on Vercel.

Runs once per cold start (from foodyx/wsgi.py, only when VERCEL is set):

1. If the repository has no migration files, generate them in /tmp.
2. Apply migrations (creates the tables on a new database; quick no-op later).
3. On a completely empty database, load the demo data (plans, super admin,
   demo restaurant) unless FOODYX_SEED_DEMO=0.

Any failure is logged (Vercel → Logs) and never stops the site from starting;
the setup page in core/setup_check.py then explains what is missing.
"""
import logging
import os

logger = logging.getLogger("foodyx.boot")


def prepare_database():
    from django.conf import settings
    from django.core.management import call_command

    if not getattr(settings, "DATABASE_URL", None):
        logger.warning("No Postgres DATABASE_URL found; skipping database preparation.")
        return
    try:
        temp_apps = getattr(settings, "FX_TEMP_MIGRATIONS", [])
        if temp_apps:
            logger.info("Generating migrations in /tmp for %s", ", ".join(temp_apps))
            call_command("makemigrations", *temp_apps, interactive=False, verbosity=0)
        call_command("migrate", interactive=False, verbosity=0)
    except Exception:
        logger.exception("Automatic migrate failed")
        return

    if os.environ.get("FOODYX_SEED_DEMO", "1") != "1":
        return
    try:
        from django.contrib.auth import get_user_model

        if not get_user_model().objects.exists():
            logger.info("Empty database: loading demo data")
            # A short history keeps the first start well inside Vercel's time limit.
            call_command("seed_demo", days=2)
    except Exception:
        # Another instance may be seeding at the same moment; that is fine.
        logger.exception("Automatic demo data failed")
