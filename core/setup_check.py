"""Turn database setup problems into a clear page instead of a bare 500.

On a fresh deployment the usual problems are a missing database variable or
tables that could not be created. This middleware says which one it is,
lists what to do, and logs the full error for Vercel's Logs tab.
"""
import logging
import os

from django.conf import settings
from django.db.utils import DatabaseError
from django.http import HttpResponse, HttpResponseRedirect
from django.utils.html import escape

logger = logging.getLogger("foodyx.setup")

PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>FoodyX · setup needed</title>
<style>body{{margin:0;font:15px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7fb;color:#0f172a;display:grid;place-items:center;min-height:100vh;padding:20px}}
.c{{max-width:640px;background:#fff;border:1px solid #e2e8f0;border-radius:18px;padding:30px;box-shadow:0 20px 50px -20px rgba(15,23,42,.25)}}
h1{{font-size:22px;margin:0 0 6px}}.tag{{display:inline-block;background:#eef2ff;color:#4338ca;font-weight:600;font-size:12px;padding:3px 10px;border-radius:99px;margin-bottom:12px}}
ol{{padding-left:20px}}li{{margin:8px 0}}code{{background:#f1f5f9;padding:2px 6px;border-radius:6px;font-size:13px}}.m{{color:#64748b;font-size:13px}}</style></head>
<body><div class="c"><span class="tag">FoodyX setup</span><h1>{title}</h1><p>{intro}</p><ol>{steps}</ol>
<p class="m">Technical detail: {detail}</p></div></body></html>"""

NO_DB = (
    "The database is not connected",
    "This deployment can't find a Postgres connection string, so it has no database.",
    [
        "In Vercel open the project → <b>Storage</b> → <b>Connect Database</b> → Neon, and connect it to this project "
        "(or add a <code>DATABASE_URL</code> variable under <b>Settings → Environment Variables</b>).",
        "Go to <b>Deployments</b>, open the newest one, click <b>⋯ → Redeploy</b> — variables only reach new deployments.",
        "Reload this page. Tables and demo data are created automatically on the first start.",
    ],
)
NOT_MIGRATED = (
    "The database tables are not ready yet",
    "The database is connected, but FoodyX's tables are missing. They are created automatically when the site starts.",
    [
        "Wait 30 seconds and reload this page — the first start can take a moment.",
        "Still here? In Vercel open <b>Deployments</b> → newest → <b>Logs</b> and look for "
        "<code>Automatic migrate failed</code>; that line explains why.",
        "Then click <b>⋯ → Redeploy</b> to try again.",
    ],
)
CONNECTION = (
    "FoodyX can't reach the database",
    "A connection string is set but the connection failed.",
    [
        "Open the Neon database in Vercel → <b>Storage</b> and check it is <b>Available</b> (not paused or deleted).",
        "If you added <code>DATABASE_URL</code> by hand, copy the string again — it must end with <code>sslmode=require</code>.",
        "Redeploy after changing anything.",
    ],
)


def _visible_db_vars():
    """Names (never values) of variables that look database-related."""
    keys = sorted(k for k in os.environ if any(t in k.upper() for t in ("DATABASE", "POSTGRES", "_URL", "PGHOST", "NEON")))
    return ", ".join(keys[:20]) or "none"


def classify(exc):
    msg = str(exc).lower()
    if not getattr(settings, "DATABASE_URL", None):
        return NO_DB
    if "no such table" in msg or "does not exist" in msg:
        return NOT_MIGRATED
    return CONNECTION


def setup_page(exc):
    title, intro, steps = classify(exc)
    if title == NOT_MIGRATED[0]:
        from core import vercel_boot

        if vercel_boot.LAST_ERROR:
            steps = steps + [f"Last automatic setup error: <code>{escape(vercel_boot.LAST_ERROR)}</code>"]
    if title == NO_DB[0]:
        steps = steps + [f"Database variables this deployment can see: <code>{escape(_visible_db_vars())}</code>"]
    text = str(exc).strip()
    first_line = text.splitlines()[0][:160] if text else exc.__class__.__name__
    html = PAGE.format(
        title=title, intro=intro, steps="".join(f"<li>{s}</li>" for s in steps),
        detail=f"{escape(exc.__class__.__name__)}: {escape(first_line)}",
    )
    return HttpResponse(html, status=503)


def error_page(exc):
    """Short reason + where it happened (no settings, no variables)."""
    import traceback

    frames = traceback.extract_tb(exc.__traceback__)
    ours = [f for f in frames if "site-packages" not in f.filename and "/python3" not in f.filename]
    where = ours[-1] if ours else (frames[-1] if frames else None)
    location = f"{where.filename.split('/var/task/')[-1]}, line {where.lineno}, in {where.name}" if where else "unknown"
    text = str(exc).strip()
    html = PAGE.format(
        title="Something went wrong on this page",
        intro="FoodyX hit an error while building this page. Send this box to your developer.",
        steps=f"<li><b>Error:</b> <code>{escape(exc.__class__.__name__)}: {escape(text.splitlines()[0][:300] if text else '')}</code></li>"
              f"<li><b>Where:</b> <code>{escape(location)}</code></li>",
        detail="Set FOODYX_HIDE_ERRORS=1 in Vercel to show a plain error page instead.",
    )
    return HttpResponse(html, status=500)


class SetupCheckMiddleware:
    retried = False

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        # Only on Vercel: locally you want Django's normal debug page.
        if getattr(settings, "ON_VERCEL", False) and isinstance(exception, DatabaseError):
            logger.exception("Database problem while serving %s", request.path)
            # Tables missing: run the automatic setup again once per instance,
            # then reload the page the visitor asked for.
            if classify(exception) is NOT_MIGRATED and not SetupCheckMiddleware.retried:
                SetupCheckMiddleware.retried = True
                from django.db import connection

                from core.vercel_boot import prepare_database

                try:
                    connection.close()
                except Exception:
                    pass
                if prepare_database():
                    return HttpResponseRedirect(request.get_full_path())
            return setup_page(exception)
        if getattr(settings, "ON_VERCEL", False) and os.environ.get("FOODYX_HIDE_ERRORS") != "1":
            logger.exception("Error while serving %s", request.path)
            return error_page(exception)
        return None
