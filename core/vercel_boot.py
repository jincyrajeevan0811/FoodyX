"""Prepare the database automatically on Vercel.

Runs once per cold start (from foodyx/wsgi.py, only when VERCEL is set) and
again from the setup page if tables are still missing:

1. If the repository has no migration files, generate them in /tmp.
2. Take a database lock so only one Vercel instance creates tables at a time.
3. Apply migrations. If an earlier, interrupted attempt left a half-built
   database that holds no FoodyX data yet, clear it and build it again.
4. On a completely empty database, load the demo data (plans, super admin,
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
LOCK_ID = 7_301_955  # arbitrary number shared by all FoodyX instances


def _remember(step, exc):
    global LAST_ERROR
    text = str(exc).strip()
    LAST_ERROR = f"{step}: {exc.__class__.__name__}: {text.splitlines()[0][:300] if text else ''}"
    logger.error("Automatic %s failed\n%s", step, traceback.format_exc())


def _alias_and_lock():
    """Connection to migrate with, and whether a session lock works on it."""
    from django.conf import settings

    alias = "direct" if "direct" in settings.DATABASES else "default"
    host = str(settings.DATABASES[alias].get("HOST", ""))
    return alias, "-pooler" not in host  # PgBouncer (transaction mode) can't hold session locks


def _wipe_if_unused(connection):
    """Drop leftover tables, but only when no FoodyX data can exist yet."""
    tables = connection.introspection.table_names()
    if "core_user" in tables:
        return False
    with connection.cursor() as cur:
        for name in tables:
            cur.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
    logger.warning("Cleared %d leftover tables from an interrupted setup", len(tables))
    return True


def _migrate(alias):
    from django.core.management import call_command
    from django.db import connections
    from django.db.utils import ProgrammingError

    try:
        call_command("migrate", database=alias, interactive=False, verbosity=0)
    except ProgrammingError as exc:
        if "already exists" not in str(exc):
            raise
        # Half-built database from an interrupted attempt.
        # Keep the same connection open: it holds the setup lock.
        conn = connections[alias]
        if _wipe_if_unused(conn):
            call_command("migrate", database=alias, interactive=False, verbosity=0)
        else:
            call_command("migrate", database=alias, interactive=False, verbosity=0, fake_initial=True)


def prepare_database():
    """Returns True when the tables are in place."""
    global LAST_ERROR
    from django.conf import settings
    from django.core.management import call_command
    from django.db import connections

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

    alias, can_lock = _alias_and_lock()
    conn = connections[alias]
    try:
        if can_lock:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_lock(%s)", [LOCK_ID])
        try:
            _migrate(alias)
            LAST_ERROR = ""
            _seed_if_empty()
        finally:
            if can_lock:
                try:
                    with conn.cursor() as cur:
                        cur.execute("SELECT pg_advisory_unlock(%s)", [LOCK_ID])
                except Exception:
                    pass
            conn.close()
    except Exception as exc:
        _remember("migrate", exc)
        return False

    return True


def _seed_if_empty():
    """Load demo data into an empty database (runs while holding the lock)."""
    from django.core.management import call_command

    if os.environ.get("FOODYX_SEED_DEMO", "1") != "1":
        return
    try:
        from django.contrib.auth import get_user_model

        if not get_user_model().objects.exists():
            logger.info("Empty database: loading demo data")
            # A short history keeps the first start well inside Vercel's time limit.
            call_command("seed_demo", days=2)
    except Exception as exc:
        _remember("demo data", exc)
