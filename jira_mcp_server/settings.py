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

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "django-insecure-change-me")
DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() == "true"
_allowed_hosts = {
    h.strip()
    for h in os.getenv("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    if h.strip()
}
_allowed_hosts.update({"127.0.0.1", "localhost", "testserver"})
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

JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://api.atlassian.com").rstrip("/")
JIRA_CLOUD_ID = os.getenv("JIRA_CLOUD_ID", "")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN", "")

_ALLOWED = os.getenv("ALLOWED_PROJECT_KEYS", "").strip()
ALLOWED_PROJECT_KEYS = {k.strip().upper() for k in _ALLOWED.split(",") if k.strip()}

MCP_API_KEY = os.getenv("MCP_API_KEY", "")

WAHA_DB_HOST = os.getenv("WAHA_DB_HOST", "127.0.0.1")
WAHA_DB_PORT = int(os.getenv("WAHA_DB_PORT", "5432"))
WAHA_DB_NAME = os.getenv("WAHA_DB_NAME", "postgres")
WAHA_DB_USER = os.getenv("WAHA_DB_USER", "postgres")
WAHA_DB_PASSWORD = os.getenv("WAHA_DB_PASSWORD", "postgres")
WAHA_DB_SSLMODE = os.getenv("WAHA_DB_SSLMODE", "prefer")

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
        "auth",
    ],
    "icons": {
        "auth": "fas fa-users-cog",
        "auth.user": "fas fa-user",
        "auth.Group": "fas fa-users",
        "mcp_gateway": "fas fa-plug",
        "mcp_gateway.AccessLog": "fas fa-clock-rotate-left",
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
