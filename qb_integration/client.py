from __future__ import annotations

from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any

import requests
from django.conf import settings
from .models import QuickBooksConfig


class QuickBooksClientError(Exception):
    pass


class QuickBooksClient:
    TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    API_BASE_URLS = {
        "sandbox": "https://sandbox-quickbooks.api.intuit.com",
        "production": "https://quickbooks.api.intuit.com",
    }

    def __init__(self) -> None:
        config = QuickBooksConfig.objects.first()
        
        client_id = config.client_id if config and config.client_id else settings.QUICKBOOKS_CLIENT_ID
        client_secret = config.client_secret if config and config.client_secret else settings.QUICKBOOKS_CLIENT_SECRET
        refresh_token = config.refresh_token if config and config.refresh_token else settings.QUICKBOOKS_REFRESH_TOKEN
        realm_id = config.realm_id if config and config.realm_id else settings.QUICKBOOKS_REALM_ID
        environment = (config.environment if config and config.environment else settings.QUICKBOOKS_ENVIRONMENT or "sandbox").strip().lower()

        if not client_id:
            raise QuickBooksClientError("QUICKBOOKS_CLIENT_ID is required")
        if not client_secret:
            raise QuickBooksClientError("QUICKBOOKS_CLIENT_SECRET is required")
        if not refresh_token:
            raise QuickBooksClientError("QUICKBOOKS_REFRESH_TOKEN is required")
        if not realm_id:
            raise QuickBooksClientError("QUICKBOOKS_REALM_ID is required")
        if environment not in self.API_BASE_URLS:
            raise QuickBooksClientError(
                "QUICKBOOKS_ENVIRONMENT must be one of: sandbox, production"
            )

        self.client_id = client_id
        self.client_secret = client_secret
        self.environment = environment
        self.base_url = self.API_BASE_URLS[environment]
        self.realm_id = str(realm_id).strip()
        self._refresh_token = refresh_token
        self._access_token = ""
        self._access_token_expires_at: datetime | None = None
        self._token_lock = Lock()

        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    @property
    def refresh_token(self) -> str:
        return self._refresh_token

    def token_state(self) -> dict[str, Any]:
        return {
            "realmId": self.realm_id,
            "environment": self.environment,
            "hasAccessToken": bool(self._access_token),
            "hasRefreshToken": bool(self._refresh_token),
            "accessTokenExpiresAt": self._access_token_expires_at.isoformat()
            if self._access_token_expires_at
            else None,
        }

    def _token_is_valid(self) -> bool:
        if not self._access_token or not self._access_token_expires_at:
            return False
        refresh_buffer = timedelta(seconds=60)
        return datetime.now(timezone.utc) + refresh_buffer < self._access_token_expires_at

    def _refresh_access_token(self) -> None:
        response = requests.post(
            self.TOKEN_URL,
            data={
                "grant_type": "refresh_token",
                "refresh_token": self._refresh_token,
            },
            auth=(self.client_id, self.client_secret),
            headers={"Accept": "application/json"},
            timeout=30,
        )
        if response.status_code >= 400:
            raise QuickBooksClientError(
                f"QuickBooks token refresh failed {response.status_code}: {response.text[:500]}"
            )

        payload = response.json()
        access_token = str(payload.get("access_token") or "").strip()
        if not access_token:
            raise QuickBooksClientError("QuickBooks token refresh succeeded without access_token")

        expires_in_raw = payload.get("expires_in", 3600)
        try:
            expires_in = max(1, int(expires_in_raw))
        except (TypeError, ValueError) as exc:
            raise QuickBooksClientError(f"Invalid QuickBooks expires_in value: {expires_in_raw}") from exc

        refreshed_token = str(payload.get("refresh_token") or "").strip()
        realm_id = str(payload.get("realmId") or "").strip()

        self._access_token = access_token
        self._access_token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        
        db_updates = False
        if refreshed_token and refreshed_token != self._refresh_token:
            self._refresh_token = refreshed_token
            db_updates = True
        if realm_id and realm_id != self.realm_id:
            self.realm_id = realm_id
            db_updates = True
            
        if db_updates:
            config = QuickBooksConfig.objects.first()
            if config:
                config.refresh_token = self._refresh_token
                config.realm_id = self.realm_id
                config.save()

    def _ensure_access_token(self) -> None:
        if self._token_is_valid():
            return
        with self._token_lock:
            if self._token_is_valid():
                return
            self._refresh_access_token()

    def _build_url(self, path: str, *, realm_id: str | None = None) -> str:
        clean_path = path.strip()
        if not clean_path:
            raise QuickBooksClientError("QuickBooks API path is required")
        if clean_path.startswith("http://") or clean_path.startswith("https://"):
            return clean_path

        company_id = (realm_id or self.realm_id).strip()
        if not company_id:
            raise QuickBooksClientError("QuickBooks realm id is required")

        normalized_path = clean_path[1:] if clean_path.startswith("/") else clean_path
        return f"{self.base_url}/v3/company/{company_id}/{normalized_path}"

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        realm_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_access_token()

        request_headers = {"Authorization": f"Bearer {self._access_token}"}
        if headers:
            request_headers.update(headers)

        full_url = self._build_url(path, realm_id=realm_id)
        
        import time
        from .models import QuickBooksAuditLog
        import json as python_json
        
        start_time = time.time()
        req_body = ""
        if json is not None:
            req_body = python_json.dumps(json)
        elif data is not None:
            req_body = str(data)
            
        success = False
        status_code = None
        resp_body = ""
        
        try:
            response = self.session.request(
                method=method,
                url=full_url,
                params=params,
                json=json,
                data=data,
                headers=request_headers,
                timeout=timeout,
            )
            status_code = response.status_code
            resp_body = response.text
            
            if response.status_code >= 400:
                raise QuickBooksClientError(
                    f"QuickBooks API error {response.status_code}: {response.text[:500]}"
                )
            success = True
            if not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise QuickBooksClientError("QuickBooks API returned non-JSON response") from exc
        finally:
            QuickBooksAuditLog.objects.create(
                method=method.upper()[:10],
                url=full_url[:1024],
                status_code=status_code,
                request_body=req_body,
                response_body=resp_body,
                success=success,
                duration_ms=int((time.time() - start_time) * 1000)
            )

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        realm_id: str | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "GET",
            path,
            params=params,
            headers=headers,
            timeout=timeout,
            realm_id=realm_id,
        )

    def post(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: dict[str, str] | None = None,
        timeout: int = 30,
        realm_id: str | None = None,
    ) -> dict[str, Any]:
        return self.request(
            "POST",
            path,
            params=params,
            json=json,
            data=data,
            headers=headers,
            timeout=timeout,
            realm_id=realm_id,
        )

    def query(self, sql: str, *, minor_version: int | None = None) -> dict[str, Any]:
        statement = (sql or "").strip()
        if not statement:
            raise QuickBooksClientError("QuickBooks query SQL is required")

        params: dict[str, Any] = {"query": statement}
        if minor_version is not None:
            params["minorversion"] = int(minor_version)
        return self.get("query", params=params)

    def get_company_info(self, *, minor_version: int | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if minor_version is not None:
            params["minorversion"] = int(minor_version)
        return self.get(f"companyinfo/{self.realm_id}", params=params or None)