#!/usr/bin/env python3
"""Generate a Google OAuth2 refresh token for Sheets + Calendar.

Usage:
  python scripts/get_refresh_token.py         # prints URL and prompts for pasted code
  python scripts/get_refresh_token.py --listen 8080  # start local server on port 8080 and capture code
  python scripts/get_refresh_token.py --write-env  # save returned refresh token into .env

The script reads client ID/secret/redirect URI and scopes from the repository .env file.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests


ENV_PATH = pathlib.Path(__file__).resolve().parents[1] / ".env"


def load_env(path: pathlib.Path) -> dict:
    data = {}
    if not path.exists():
        return data
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"').strip("'")
    return data


def write_env(path: pathlib.Path, updates: dict) -> None:
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    out = []
    handled = set()
    for line in lines:
        if not line or line.strip().startswith("#") or "=" not in line:
            out.append(line)
            continue
        k, _ = line.split("=", 1)
        k = k.strip()
        if k in updates:
            out.append(f"{k}={updates[k]}")
            handled.add(k)
        else:
            out.append(line)
    for k, v in updates.items():
        if k not in handled:
            out.append(f"{k}={v}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def build_auth_url(client_id: str, redirect_uri: str, scopes: list[str]) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)


def exchange_code(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    data = {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }
    r = requests.post("https://oauth2.googleapis.com/token", data=data, timeout=30)
    r.raise_for_status()
    return r.json()


class CodeHandler(BaseHTTPRequestHandler):
    server_version = "GetRefreshToken/1.0"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        code = qs.get("code", [None])[0]
        if code:
            self.server.code = code
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>Authorization received</h1><p>You can close this window.</p></body></html>")
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h1>No code found</h1></body></html>")


def run_local_server(port: int, timeout: int = 300) -> str | None:
    server = HTTPServer(("", port), CodeHandler)
    server.code = None

    def serve():
        with server:
            server.handle_request()

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    th.join(timeout)
    return getattr(server, "code", None)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--listen", nargs="?", const=8080, type=int, help="Start a local HTTP server to capture the code on the given port")
    p.add_argument("--write-env", action="store_true", help="Write the returned refresh token into .env as GOOGLE_SHEETS_REFRESH_TOKEN")
    args = p.parse_args()

    env = load_env(ENV_PATH)
    cid = env.get("GOOGLE_SHEETS_CLIENT_ID") or os.getenv("GOOGLE_SHEETS_CLIENT_ID")
    csecret = env.get("GOOGLE_SHEETS_CLIENT_SECRET") or os.getenv("GOOGLE_SHEETS_CLIENT_SECRET")
    redirect = env.get("GOOGLE_SHEETS_REDIRECT_URI") or os.getenv("GOOGLE_SHEETS_REDIRECT_URI") or "http://localhost:8080"

    if not cid or not csecret:
        print("Missing GOOGLE_SHEETS_CLIENT_ID or GOOGLE_SHEETS_CLIENT_SECRET in .env or environment.")
        raise SystemExit(1)

    sheets_scopes = [s for s in (env.get("GOOGLE_SHEETS_SCOPES") or os.getenv("GOOGLE_SHEETS_SCOPES") or "").split(",") if s]
    cal_scopes = [s for s in (env.get("GOOGLE_CALENDAR_SCOPES") or os.getenv("GOOGLE_CALENDAR_SCOPES") or "").split(",") if s]
    scopes = []
    for s in sheets_scopes + cal_scopes:
        s = s.strip()
        if s and s not in scopes:
            scopes.append(s)
    if not scopes:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/calendar"]

    auth_url = build_auth_url(cid, redirect, scopes)
    print("Open this URL in a browser and grant access:\n")
    print(auth_url)
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    code = None
    if args.listen:
        port = int(args.listen)
        print(f"Listening on http://localhost:{port}/ to capture the code...\nMake sure your OAuth redirect URI matches this address.")
        code = run_local_server(port)
        if not code:
            print("No code received via local server (timeout).")

    if not code:
        code = input("Paste the authorization code here: ").strip()

    if not code:
        print("No authorization code provided. Exiting.")
        raise SystemExit(1)

    print("Exchanging code for tokens...")
    token_response = exchange_code(code, cid, csecret, redirect)
    print(json.dumps(token_response, indent=2))

    refresh = token_response.get("refresh_token")
    if refresh and args.write_env:
        write_env(ENV_PATH, {"GOOGLE_SHEETS_REFRESH_TOKEN": refresh})
        print(f"Wrote refresh token to {ENV_PATH}")


if __name__ == "__main__":
    main()
