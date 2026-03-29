import os

from . import sqlite_patch  # noqa: F401
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "jira_mcp_server.settings")

application = get_asgi_application()
