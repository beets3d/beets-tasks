import os

from . import sqlite_patch  # noqa: F401
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jira_mcp_server.settings")

application = get_wsgi_application()
