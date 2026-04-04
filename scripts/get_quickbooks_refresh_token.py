#!/usr/bin/env python3
"""Generate QuickBooks OAuth2 refresh token and realm ID.

Usage:
  python3 scripts/get_quickbooks_refresh_token.py
  python3 scripts/get_quickbooks_refresh_token.py --listen 8000
  python3 scripts/get_quickbooks_refresh_token.py --write-env

The script reads QuickBooks OAuth settings from repository .env:
  QUICKBOOKS_CLIENT_ID
  QUICKBOOKS_CLIENT_SECRET
  QUICKBOOKS_REDIRECT_URI
  QUICKBOOKS_ENVIRONMENT
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests


ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"
AUTH_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
DEFAULT_SCOPE = "com.intuit.quickbooks.accounting"


def load_env(path: pathlib.Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def write_env(path: pathlib.Path, updates: dict[str, str]) -> None:
    lines: list[str] = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()

    out: list[str] = []
    handled: set[str] = set()
    for line in lines:
        if not line or line.strip().startswith("#") or "=" not in line:
            out.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            out.append(f"{key}={updates[key]}")
            handled.add(key)
        else:
            out.append(line)

    for key, value in updates.items():
        if key not in handled:
            out.append(f"{key}={value}")

    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def build_auth_url(client_id: str, redirect_uri: str, scopes: list[str], state: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
    }
    return AUTH_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict[str, object]:
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
    response.raise_for_status()
    return response.json()


def parse_code_input(raw: str) -> tuple[str, str | None]:
    value = (raw or "").strip()
    if not value:
        return "", None

    if value.startswith("http://") or value.startswith("https://"):
        parsed = urllib.parse.urlparse(value)
        qs = urllib.parse.parse_qs(parsed.query)
        code = (qs.get("code", [""])[0] or "").strip()
        realm_id = (qs.get("realmId", [""])[0] or "").strip() or None
        return code, realm_id

    return value, None


class CallbackHandler(BaseHTTPRequestHandler):
    server_version = "QuickBooksOAuth/1.0"

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        self.server.code = (query.get("code", [None])[0] or "").strip()  # type: ignore[attr-defined]
        self.server.realm_id = (query.get("realmId", [None])[0] or "").strip()  # type: ignore[attr-defined]
        self.server.state = (query.get("state", [None])[0] or "").strip()  # type: ignore[attr-defined]
        self.server.oauth_error = (query.get("error", [None])[0] or "").strip()  # type: ignore[attr-defined]

        if self.server.code:  # type: ignore[attr-defined]
            body = (
                "<html><body><h1>QuickBooks authorization received</h1>"
                "<p>You can close this window.</p></body></html>"
            )
        elif self.server.oauth_error:  # type: ignore[attr-defined]
            body = (
                "<html><body><h1>QuickBooks authorization failed</h1>"
                "<p>Please check your terminal for details.</p></body></html>"
            )
        else:
            body = "<html><body><h1>No authorization code found</h1></body></html>"

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


def run_local_server(port: int, timeout: int = 300) -> tuple[str | None, str | None, str | None, str | None]:
    server = HTTPServer(("", port), CallbackHandler)
    server.code = None
    server.realm_id = None
    server.state = None
    server.oauth_error = None

    def serve_once() -> None:
        with server:
            server.handle_request()

    thread = threading.Thread(target=serve_once, daemon=True)
    thread.start()
    thread.join(timeout)

    return (
        getattr(server, "code", None),
        getattr(server, "realm_id", None),
        getattr(server, "state", None),
        getattr(server, "oauth_error", None),
    )


def _default_port_from_redirect(redirect_uri: str) -> int:
    try:
        parsed = urllib.parse.urlparse(redirect_uri)
    except Exception:
        return 8000
    if parsed.port:
        return int(parsed.port)
    if parsed.scheme == "https":
        return 443
    return 8000


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--listen",
        nargs="?",
        const=-1,
        type=int,
        help="Start local callback server on the given port (defaults to port from QUICKBOOKS_REDIRECT_URI)",
    )
    parser.add_argument("--write-env", action="store_true", help="Write QUICKBOOKS_REFRESH_TOKEN and QUICKBOOKS_REALM_ID to .env")
    args = parser.parse_args()

    env = load_env(ENV_PATH)
    client_id = env.get("QUICKBOOKS_CLIENT_ID") or os.getenv("QUICKBOOKS_CLIENT_ID")
    client_secret = env.get("QUICKBOOKS_CLIENT_SECRET") or os.getenv("QUICKBOOKS_CLIENT_SECRET")
    redirect_uri = env.get("QUICKBOOKS_REDIRECT_URI") or os.getenv("QUICKBOOKS_REDIRECT_URI") or "http://localhost:8000/qb/callback"
    scopes_raw = env.get("QUICKBOOKS_SCOPES") or os.getenv("QUICKBOOKS_SCOPES") or DEFAULT_SCOPE

    if not client_id or not client_secret:
        print("Missing QUICKBOOKS_CLIENT_ID or QUICKBOOKS_CLIENT_SECRET in .env or environment.")
        raise SystemExit(1)

    scopes = [scope.strip() for scope in scopes_raw.split(",") if scope.strip()]
    if not scopes:
        scopes = [DEFAULT_SCOPE]

    state = secrets.token_urlsafe(24)
    auth_url = build_auth_url(client_id, redirect_uri, scopes, state)

    print("Open this URL in a browser and approve QuickBooks access:\n")
    print(auth_url)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    code = ""
    realm_id: str | None = None

    if args.listen is not None:
        port = _default_port_from_redirect(redirect_uri) if args.listen == -1 else int(args.listen)
        print(
            f"\nListening on http://localhost:{port}/ for callback. "
            "Ensure QUICKBOOKS_REDIRECT_URI uses this same host/port/path."
        )
        got_code, got_realm, got_state, oauth_error = run_local_server(port)
        if oauth_error:
            print(f"QuickBooks OAuth returned error: {oauth_error}")
            raise SystemExit(1)
        if got_state and got_state != state:
            print("OAuth state mismatch. Try again.")
            raise SystemExit(1)
        code = (got_code or "").strip()
        realm_id = (got_realm or "").strip() or None
        if not code:
            print("No authorization code received via local callback server.")

    if not code:
        pasted = input("\nPaste the authorization code or full callback URL here: ").strip()
        parsed_code, parsed_realm = parse_code_input(pasted)
        code = parsed_code
        realm_id = realm_id or parsed_realm

    if not code:
        print("No authorization code provided. Exiting.")
        raise SystemExit(1)

    print("\nExchanging code for tokens...")
    token_payload = exchange_code(code, client_id, client_secret, redirect_uri)
    print(json.dumps(token_payload, indent=2))

    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    token_realm = str(token_payload.get("realmId") or "").strip()
    resolved_realm_id = token_realm or (realm_id or "")

    if not refresh_token:
        print("\nNo refresh_token returned. Ensure app scopes include QuickBooks Accounting and consent was granted.")
        raise SystemExit(1)

    print("\nResolved credentials:")
    print(f"- refresh token present: {bool(refresh_token)}")
    print(f"- realm id: {resolved_realm_id or '(missing)'}")

    if args.write_env:
        updates = {"QUICKBOOKS_REFRESH_TOKEN": refresh_token}
        if resolved_realm_id:
            updates["QUICKBOOKS_REALM_ID"] = resolved_realm_id
        write_env(ENV_PATH, updates)
        print(f"\nWrote {', '.join(sorted(updates.keys()))} to {ENV_PATH}")
    else:
        print("\nTip: run again with --write-env to persist QUICKBOOKS_REFRESH_TOKEN and QUICKBOOKS_REALM_ID.")


if __name__ == "__main__":
    main()
