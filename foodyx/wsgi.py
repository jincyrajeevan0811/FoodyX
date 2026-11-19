import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "foodyx.settings")
application = get_wsgi_application()

if os.environ.get("VERCEL"):
    # Create/upgrade the database tables (and demo data on an empty
    # database) once per cold start. See core/vercel_boot.py.
    from core.vercel_boot import prepare_database

    prepare_database()

# Vercel's Python runtime looks for a variable called `app`.
app = application
