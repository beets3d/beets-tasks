import urllib.parse
from django.conf import settings
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
import requests
import pathlib
import os
from .models import QuickBooksConfig

AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
DEFAULT_SCOPE = "com.intuit.quickbooks.accounting"
ENV_PATH = pathlib.Path(settings.BASE_DIR) / ".env"


def write_env(path: pathlib.Path, updates: dict[str, str]) -> None:
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    out: list[str] = []
    for line in lines:
        if "=" not in line or line.startswith("#"):
            out.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in updates:
            out.append(f"{key}='{updates[key]}'")
            del updates[key]
        else:
            out.append(line)

    for k, v in updates.items():
        out.append(f"{k}='{v}'")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def login(request: HttpRequest) -> HttpResponse:
    config = QuickBooksConfig.objects.first()
    client_id = config.client_id if config else settings.QUICKBOOKS_CLIENT_ID
    redirect_uri = config.redirect_uri if config else settings.QUICKBOOKS_REDIRECT_URI
    if not client_id or not redirect_uri:
        return HttpResponse("Missing client_id or redirect_uri", status=500)

    params = {
        "client_id": client_id,
        "response_type": "code",
        "scope": DEFAULT_SCOPE,
        "redirect_uri": redirect_uri,
        "state": "qb_admin",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"
    return HttpResponseRedirect(url)


def callback(request: HttpRequest) -> HttpResponse:
    code = request.GET.get("code")
    realm_id = request.GET.get("realmId")
    state = request.GET.get("state")
    
    if not code:
        return HttpResponse("Missing code in callback", status=400)

    config = QuickBooksConfig.objects.first()
    client_id = config.client_id if config else settings.QUICKBOOKS_CLIENT_ID
    client_secret = config.client_secret if config else settings.QUICKBOOKS_CLIENT_SECRET
    redirect_uri = config.redirect_uri if config else settings.QUICKBOOKS_REDIRECT_URI

    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
        headers={"Accept": "application/json"},
        timeout=30,
    )
    if response.status_code >= 400:
        return HttpResponse(f"Token exchange failed: {response.text}", status=400)

    payload = response.json()
    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        return HttpResponse("No refresh token in response", status=400)

    updates = {"QUICKBOOKS_REFRESH_TOKEN": refresh_token}
    if realm_id:
        updates["QUICKBOOKS_REALM_ID"] = realm_id

    write_env(ENV_PATH, updates)

    if config:
        config.refresh_token = refresh_token
        if realm_id:
            config.realm_id = realm_id
        config.save()
    
    # Reload settings temporarily for the running process if possible, 
    # but normally requiring a restart is fine for .env changes.
    settings.QUICKBOOKS_REFRESH_TOKEN = refresh_token
    if realm_id:
        settings.QUICKBOOKS_REALM_ID = realm_id

    return HttpResponse(
        "Successfully authenticated with QuickBooks and saved to .env! "
        "You may need to restart the server to fully apply changes."
    )

REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"

def launch(request: HttpRequest) -> HttpResponse:
    """Launch URL for Intuit App Center. Redirects user to the system dashboard."""
    return HttpResponseRedirect("/admin/qb_integration/quickbooksconfig/")


def disconnect(request: HttpRequest) -> HttpResponse:
    """Disconnect URL. Clears the tokens from the environment and attempts to revoke from Intuit."""
    config = QuickBooksConfig.objects.first()
    client_id = config.client_id if config else settings.QUICKBOOKS_CLIENT_ID
    client_secret = config.client_secret if config else settings.QUICKBOOKS_CLIENT_SECRET
    refresh_token = config.refresh_token if config and config.refresh_token else getattr(settings, "QUICKBOOKS_REFRESH_TOKEN", None)

    # Attempt to revoke token remotely if it exists
    if refresh_token and refresh_token != "replace-with-quickbooks-refresh-token":
        try:
            requests.post(
                REVOKE_URL,
                json={"token": refresh_token},
                auth=(client_id, client_secret),
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                timeout=10,
            )
        except Exception:
            pass # Ignore network errors during revocation

    # Clear from .env
    updates = {
        "QUICKBOOKS_REFRESH_TOKEN": "replace-with-quickbooks-refresh-token",
        "QUICKBOOKS_REALM_ID": "replace-with-quickbooks-realm-id",
    }
    write_env(ENV_PATH, updates)

    if config:
        config.refresh_token = ""
        config.realm_id = ""
        config.save()

    # Clear dynamically
    settings.QUICKBOOKS_REFRESH_TOKEN = "replace-with-quickbooks-refresh-token"
    settings.QUICKBOOKS_REALM_ID = "replace-with-quickbooks-realm-id"

    # Some requests to disconnect are webhooks from Intuit. If it's a browser, show text.
    return HttpResponse(
        "Successfully disconnected from QuickBooks and cleared tokens. "
        "You may need to restart the server to fully apply changes."
    )
