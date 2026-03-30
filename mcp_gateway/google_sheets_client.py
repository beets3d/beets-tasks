from __future__ import annotations

from typing import Any
import threading
from typing import Optional
from threading import Lock, Event

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth import exceptions as auth_exceptions


class GoogleSheetsClientError(Exception):
    pass


class GoogleSheetsClient:
    def __init__(self) -> None:
        if not settings.GOOGLE_SHEETS_CLIENT_ID:
            raise GoogleSheetsClientError("GOOGLE_SHEETS_CLIENT_ID is required")
        if not settings.GOOGLE_SHEETS_CLIENT_SECRET:
            raise GoogleSheetsClientError("GOOGLE_SHEETS_CLIENT_SECRET is required")
        if not settings.GOOGLE_SHEETS_REFRESH_TOKEN:
            raise GoogleSheetsClientError("GOOGLE_SHEETS_REFRESH_TOKEN is required")

        creds = Credentials(
            token=None,
            refresh_token=settings.GOOGLE_SHEETS_REFRESH_TOKEN,
            token_uri=settings.GOOGLE_SHEETS_TOKEN_URI,
            client_id=settings.GOOGLE_SHEETS_CLIENT_ID,
            client_secret=settings.GOOGLE_SHEETS_CLIENT_SECRET,
            scopes=settings.GOOGLE_SHEETS_SCOPES,
        )
        # keep creds and a lock for thread-safe refresh
        self.creds = creds
        self._creds_lock = Lock()
        try:
            with self._creds_lock:
                self.creds.refresh(Request())
        except Exception as exc:
            raise GoogleSheetsClientError(f"Failed to refresh credentials: {exc}") from exc
        self.service = build("sheets", "v4", credentials=self.creds, cache_discovery=False)

        # start background refresher thread
        self._stop_event: Event = Event()
        interval = getattr(settings, "GOOGLE_SHEETS_REFRESH_INTERVAL_SECONDS", 2700)
        try:
            interval = int(interval)
        except Exception:
            interval = 2700
        self._refresh_interval = max(60, interval)
        self._refresher_thread: Optional[threading.Thread] = None
        self._start_refresher()

    @staticmethod
    def _resolve_spreadsheet_id(spreadsheet_id: str | None) -> str:
        candidate = (spreadsheet_id or settings.GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID).strip()
        if not candidate:
            raise GoogleSheetsClientError("spreadsheetId is required")
        return candidate

    def _execute(self, request: Any) -> dict[str, Any]:
        # ensure token is fresh before executing
        try:
            self._refresh_if_needed()
        except Exception:
            # proceed and let the request surface errors
            pass
        try:
            result = request.execute()
        except HttpError as exc:
            raise GoogleSheetsClientError(f"Google Sheets API error: {exc}") from exc
        except Exception as exc:
            raise GoogleSheetsClientError(str(exc)) from exc
        if isinstance(result, dict):
            return result
        return {"result": result}

    def _refresh_if_needed(self) -> None:
        """Refresh credentials if expired or token missing."""
        if not getattr(self, "creds", None):
            return
        try:
            if not self.creds.valid or self.creds.expired or not self.creds.token:
                with self._creds_lock:
                    if not self.creds.valid or self.creds.expired or not self.creds.token:
                        self.creds.refresh(Request())
        except auth_exceptions.RefreshError as exc:
            raise GoogleSheetsClientError(f"Failed to refresh access token: {exc}") from exc
        except Exception as exc:
            raise GoogleSheetsClientError(f"Unexpected error refreshing token: {exc}") from exc

    def _refresher_loop(self) -> None:
        while not self._stop_event.wait(self._refresh_interval):
            try:
                self._refresh_if_needed()
            except Exception:
                pass

    def _start_refresher(self) -> None:
        if self._refresher_thread and self._refresher_thread.is_alive():
            return
        th = threading.Thread(target=self._refresher_loop, daemon=True, name="gsheets-refresher")
        th.start()
        self._refresher_thread = th

    def close(self) -> None:
        try:
            self._stop_event.set()
        except Exception:
            pass

    def get_spreadsheet(self, *, spreadsheet_id: str | None = None, ranges: list[str] | None = None) -> dict[str, Any]:
        return self._execute(
            self.service.spreadsheets().get(
                spreadsheetId=self._resolve_spreadsheet_id(spreadsheet_id),
                ranges=ranges or None,
                includeGridData=False,
            )
        )

    def get_values(
        self,
        *,
        spreadsheet_id: str | None = None,
        range_name: str,
        major_dimension: str | None = None,
    ) -> dict[str, Any]:
        if not range_name or not range_name.strip():
            raise GoogleSheetsClientError("range is required")
        return self._execute(
            self.service.spreadsheets().values().get(
                spreadsheetId=self._resolve_spreadsheet_id(spreadsheet_id),
                range=range_name,
                majorDimension=major_dimension or "ROWS",
            )
        )

    def update_values(
        self,
        *,
        spreadsheet_id: str | None = None,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
    ) -> dict[str, Any]:
        if not range_name or not range_name.strip():
            raise GoogleSheetsClientError("range is required")
        if not isinstance(values, list) or not values:
            raise GoogleSheetsClientError("values must be a non-empty 2D array")
        return self._execute(
            self.service.spreadsheets().values().update(
                spreadsheetId=self._resolve_spreadsheet_id(spreadsheet_id),
                range=range_name,
                valueInputOption=value_input_option,
                body={"values": values},
            )
        )

    def append_values(
        self,
        *,
        spreadsheet_id: str | None = None,
        range_name: str,
        values: list[list[Any]],
        value_input_option: str = "USER_ENTERED",
        insert_data_option: str = "INSERT_ROWS",
    ) -> dict[str, Any]:
        if not range_name or not range_name.strip():
            raise GoogleSheetsClientError("range is required")
        if not isinstance(values, list) or not values:
            raise GoogleSheetsClientError("values must be a non-empty 2D array")
        return self._execute(
            self.service.spreadsheets().values().append(
                spreadsheetId=self._resolve_spreadsheet_id(spreadsheet_id),
                range=range_name,
                valueInputOption=value_input_option,
                insertDataOption=insert_data_option,
                body={"values": values},
            )
        )