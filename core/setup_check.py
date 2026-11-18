"""Turn database setup problems into a clear page instead of a bare 500.

On a fresh deployment the most common failures are a missing DATABASE_URL
or a database whose tables were never created (`migrate` not run). This
middleware explains which one it is and logs the full error, so the fix is
obvious from the browser and from the hosting logs.
"""
import logging

from django.conf import settings
from django.db.utils import DatabaseError
from django.http import HttpResponse
from django.utils.html import escape

logger = logging.getLogger("foodyx.setup")

PAGE = """<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>FoodyX · setup needed</title>
<style>body{{margin:0;font:15px/1.6 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;background:#f6f7fb;color:#0f172a;display:grid;place-items:center;min-height:100vh;padding:20px}}
.c{{max-width:620px;background:#fff;border:1px solid #e2e8f0;border-radius:18px;padding:30px;box-shadow:0 20px 50px -20px rgba(15,23,42,.25)}}
h1{{font-size:22px;margin:0 0 6px}}.tag{{display:inline-block;background:#eef2ff;color:#4338ca;font-weight:600;font-size:12px;padding:3px 10px;border-radius:99px;margin-bottom:12px}}
ol{{padding-left:20px}}li{{margin:8px 0}}code{{background:#f1f5f9;padding:2px 6px;border-radius:6px;font-size:13px}}.m{{color:#64748b;font-size:13px}}</style></head>
<body><div class="c"><span class="tag">FoodyX setup</span><h1>{title}</h1><p>{intro}</p><ol>{steps}</ol>
<p class="m">Technical detail: {detail}</p></div></body></html>"""

NO_DB = (
    "The database is not connected",
    "This deployment has no <code>DATABASE_URL</code>, so it fell back to a SQLite file, which can't be used on Vercel.",
    [
        "In Vercel open your project → <b>Settings → Environment Variables</b>.",
        "Add <code>DATABASE_URL</code> with your Neon / Postgres connection string "
        "(<code>postgresql://…?sslmode=require</code>) for <b>Production</b> (and Preview).",
        "Go to <b>Deployments</b>, open the latest one and click <b>Redeploy</b> — variables only apply to new deployments.",
    ],
)
NOT_MIGRATED = (
    "The database tables have not been created yet",
    "The app reached the database, but FoodyX's tables are missing. Run the migrations once against that database.",
    [
        "On your computer, in the FoodyX folder: <code>pip install -r requirements.txt</code>",
        "Point Django at the same database. PowerShell: <code>$env:DATABASE_URL=\"postgresql://…\"</code> "
        "(macOS/Linux: <code>export DATABASE_URL=\"postgresql://…\"</code>)",
        "Run <code>python manage.py makemigrations</code>, then <code>python manage.py migrate</code>, "
        "then <code>python manage.py seed_demo</code>.",
        "Reload this page — no redeploy is needed.",
    ],
)
CONNECTION = (
    "FoodyX can't reach the database",
    "<code>DATABASE_URL</code> is set but the connection failed.",
    [
        "Check the connection string in Vercel → Settings → Environment Variables (copy it again from Neon).",
        "Make sure it ends with <code>?sslmode=require</code> and the Neon project is not paused or deleted.",
        "Redeploy after changing the variable.",
    ],
)


def classify(exc):
    msg = str(exc).lower()
    if getattr(settings, "ON_VERCEL", False) and not getattr(settings, "DATABASE_URL", None):
        return NO_DB
    if "no such table" in msg or ("relation" in msg and "does not exist" in msg) or "does not exist" in msg and "table" in msg:
        return NOT_MIGRATED
    if "unable to open database" in msg or "readonly database" in msg or "read-only" in msg:
        return NO_DB
    return CONNECTION


def setup_page(exc):
    title, intro, steps = classify(exc)
    first_line = str(exc).strip().splitlines()[0][:160] if str(exc).strip() else exc.__class__.__name__
    html = PAGE.format(
        title=title, intro=intro, steps="".join(f"<li>{s}</li>" for s in steps),
        detail=f"{escape(exc.__class__.__name__)}: {escape(first_line)}",
    )
    return HttpResponse(html, status=503)


class SetupCheckMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, DatabaseError):
            logger.exception("Database problem while serving %s", request.path)
            return setup_page(exception)
        return None
