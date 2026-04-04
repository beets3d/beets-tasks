import os
from pathlib import Path

from . import sqlite_patch  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_env_file(BASE_DIR / ".env")

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY") or ""
DEBUG = (os.getenv("DJANGO_DEBUG") or "").lower() == "true"
_allowed_hosts = {
    h.strip()
    for h in (os.getenv("DJANGO_ALLOWED_HOSTS") or "").split(",")
    if h.strip()
}
_allowed_hosts.update({"127.0.0.1", "localhost", "tasks.beets3d.cn"})
ALLOWED_HOSTS = sorted(_allowed_hosts)

INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "mcp_gateway",
    "qb_integration",
    "crm",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "jira_mcp_server.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "jira_mcp_server.wsgi.application"
ASGI_APPLICATION = "jira_mcp_server.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

JIRA_BASE_URL = (os.getenv("JIRA_BASE_URL") or "").rstrip("/")
JIRA_CLOUD_ID = os.getenv("JIRA_CLOUD_ID") or ""
JIRA_EMAIL = os.getenv("JIRA_EMAIL") or ""
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN") or ""

_ALLOWED = (os.getenv("ALLOWED_PROJECT_KEYS") or "").strip()
ALLOWED_PROJECT_KEYS = {k.strip().upper() for k in _ALLOWED.split(",") if k.strip()}

MCP_API_KEY = os.getenv("MCP_API_KEY") or ""

GOOGLE_SHEETS_PROJECT_ID = os.getenv("GOOGLE_SHEETS_PROJECT_ID") or ""
GOOGLE_SHEETS_CLIENT_ID = os.getenv("GOOGLE_SHEETS_CLIENT_ID") or ""
GOOGLE_SHEETS_CLIENT_SECRET = os.getenv("GOOGLE_SHEETS_CLIENT_SECRET") or ""
GOOGLE_SHEETS_AUTH_URI = os.getenv("GOOGLE_SHEETS_AUTH_URI") or ""
GOOGLE_SHEETS_TOKEN_URI = os.getenv("GOOGLE_SHEETS_TOKEN_URI") or ""
GOOGLE_SHEETS_AUTH_PROVIDER_CERT_URL = os.getenv("GOOGLE_SHEETS_AUTH_PROVIDER_CERT_URL") or ""
GOOGLE_SHEETS_REDIRECT_URI = os.getenv("GOOGLE_SHEETS_REDIRECT_URI") or ""
GOOGLE_SHEETS_REFRESH_TOKEN = os.getenv("GOOGLE_SHEETS_REFRESH_TOKEN") or ""
GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID") or ""
GOOGLE_SHEETS_SCOPES = [
    scope.strip()
    for scope in (os.getenv("GOOGLE_SHEETS_SCOPES") or "").split(",")
    if scope.strip()
]
QUICKBOOKS_CLIENT_ID = os.getenv("QUICKBOOKS_CLIENT_ID") or ""
QUICKBOOKS_CLIENT_SECRET = os.getenv("QUICKBOOKS_CLIENT_SECRET") or ""
QUICKBOOKS_ENVIRONMENT = os.getenv("QUICKBOOKS_ENVIRONMENT") or "sandbox"
QUICKBOOKS_REDIRECT_URI = os.getenv("QUICKBOOKS_REDIRECT_URI") or ""
QUICKBOOKS_REFRESH_TOKEN = os.getenv("QUICKBOOKS_REFRESH_TOKEN") or ""
QUICKBOOKS_REALM_ID = os.getenv("QUICKBOOKS_REALM_ID") or ""

# CSRF trusted origins. Provide via env `CSRF_TRUSTED_ORIGINS` as comma-separated
# values including scheme and port, e.g. 'http://localhost:8001,http://127.0.0.1:8001'
_explicit_csrf = [
    s.strip()
    for s in (os.getenv("CSRF_TRUSTED_ORIGINS") or "http://localhost:8001,http://127.0.0.1:8001").split(",")
    if s.strip()
]

# Also include origins derived from ALLOWED_HOSTS (both http and https)
derived_csrf = []
for h in sorted(ALLOWED_HOSTS):
    if not h:
        continue
    if h in {"127.0.0.1", "localhost", "testserver"}:
        # include localhost variants already in explicit list
        continue
    if not h.startswith("http://") and not h.startswith("https://"):
        derived_csrf.append(f"https://{h}")
        derived_csrf.append(f"http://{h}")

CSRF_TRUSTED_ORIGINS = []
seen = set()
for s in _explicit_csrf + derived_csrf:
    if s not in seen:
        CSRF_TRUSTED_ORIGINS.append(s)
        seen.add(s)

# Google Calendar scopes. If not set, default to the same scopes as Google Sheets
GOOGLE_CALENDAR_SCOPES = [
    scope.strip()
    for scope in (os.getenv("GOOGLE_CALENDAR_SCOPES") or ",".join(GOOGLE_SHEETS_SCOPES)).split(",")
    if scope.strip()
]

WAHA_DB_HOST = os.getenv("WAHA_DB_HOST") or ""
WAHA_DB_PORT = int((os.getenv("WAHA_DB_PORT") or "0"))
WAHA_DB_NAME = os.getenv("WAHA_DB_NAME") or ""
WAHA_DB_USER = os.getenv("WAHA_DB_USER") or ""
WAHA_DB_PASSWORD = os.getenv("WAHA_DB_PASSWORD") or ""
WAHA_DB_SSLMODE = os.getenv("WAHA_DB_SSLMODE") or ""

JAZZMIN_SETTINGS = {
    "site_title": "Beets Task",
    "site_header": "Beets Task",
    "site_brand": "Beets Task",
    "welcome_sign": "Welcome to Beets Task",
    "copyright": "Beets Task",
    "site_logo_classes": "img-circle elevation-2",
    "show_sidebar": True,
    "navigation_expanded": True,
    "hide_apps": [],
    "hide_models": [],
    "order_with_respect_to": [
        "mcp_gateway",
    "qb_integration",
        "auth",
    ],
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",
        "mcp_gateway": "fas fa-plug",
        "mcp_gateway.AccessLog": "fas fa-clock-rotate-left",
        "qb_integration.QuickBooksConfig": "fas fa-file-invoice-dollar",
        "qb_integration.QuickBooksWebhookLog": "fas fa-list",
        "qb_integration.QuickBooksAuditLog": "fas fa-history",
        
        "crm": "fas fa-address-book",
        "crm.Customer": "fas fa-user",
    },
    "topmenu_links": [
        {"name": "Home", "url": "admin:index", "permissions": ["auth.view_user"]},
        {"model": "mcp_gateway.AccessLog"},
    ],
    "show_ui_builder": False,
    "changeform_format": "horizontal_tabs",
    "language_chooser": False,
}

JAZZMIN_UI_TWEAKS = {
    "theme": "flatly",
    "dark_mode_theme": None,
    "navbar": "navbar-white navbar-light",
    "no_navbar_border": True,
    "accent": "accent-teal",
    "navbar_small_text": False,
    "sidebar": "sidebar-light-info",
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": False,
    "sidebar_nav_flat_style": False,
    "theme_switcher": False,
}
