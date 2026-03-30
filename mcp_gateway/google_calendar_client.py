from __future__ import annotations

from typing import Any
import threading
import time
from typing import Optional
from threading import Lock, Event

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth import exceptions as auth_exceptions


class GoogleCalendarClientError(Exception):
    pass


class GoogleCalendarClient:
    def __init__(self) -> None:
        if not settings.GOOGLE_SHEETS_CLIENT_ID:
            raise GoogleCalendarClientError("GOOGLE_SHEETS_CLIENT_ID is required")
        if not settings.GOOGLE_SHEETS_CLIENT_SECRET:
            raise GoogleCalendarClientError("GOOGLE_SHEETS_CLIENT_SECRET is required")
        if not settings.GOOGLE_SHEETS_REFRESH_TOKEN:
            raise GoogleCalendarClientError("GOOGLE_SHEETS_REFRESH_TOKEN is required")

        creds = Credentials(
            token=None,
            refresh_token=settings.GOOGLE_SHEETS_REFRESH_TOKEN,
            token_uri=settings.GOOGLE_SHEETS_TOKEN_URI,
            client_id=settings.GOOGLE_SHEETS_CLIENT_ID,
            client_secret=settings.GOOGLE_SHEETS_CLIENT_SECRET,
            scopes=settings.GOOGLE_CALENDAR_SCOPES,
        )
        # store credentials so we can refresh them on-demand
        self.creds = creds
        self._creds_lock = Lock()
        try:
            with self._creds_lock:
                self.creds.refresh(Request())
        except Exception as exc:
            raise GoogleCalendarClientError(f"Failed to refresh credentials: {exc}") from exc
        self.service = build("calendar", "v3", credentials=self.creds, cache_discovery=False)

        # start background refresher thread
        self._stop_event: Event = Event()
        interval = getattr(settings, "GOOGLE_CALENDAR_REFRESH_INTERVAL_SECONDS", 2700)
        try:
            interval = int(interval)
        except Exception:
            interval = 2700
        self._refresh_interval = max(60, interval)
        self._refresher_thread: Optional[threading.Thread] = None
        self._start_refresher()

    @staticmethod
    def _execute(request: Any) -> dict[str, Any]:
        try:
            result = request.execute()
        except HttpError as exc:
            # If the error indicates authorization, bubble up for caller to handle
            raise GoogleCalendarClientError(f"Google Calendar API error: {exc}") from exc
        except Exception as exc:
            raise GoogleCalendarClientError(str(exc)) from exc
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
                    # double-check inside lock
                    if not self.creds.valid or self.creds.expired or not self.creds.token:
                        self.creds.refresh(Request())
        except auth_exceptions.RefreshError as exc:
            raise GoogleCalendarClientError(f"Failed to refresh access token: {exc}") from exc
        except Exception as exc:
            raise GoogleCalendarClientError(f"Unexpected error refreshing token: {exc}") from exc

    def _refresher_loop(self) -> None:
        """Background loop that periodically refreshes credentials."""
        while not self._stop_event.wait(self._refresh_interval):
            try:
                self._refresh_if_needed()
            except Exception:
                # swallow exceptions to keep the background thread alive; errors will surface on request
                pass

    def _start_refresher(self) -> None:
        if self._refresher_thread and self._refresher_thread.is_alive():
            return
        th = threading.Thread(target=self._refresher_loop, daemon=True, name="gcal-refresher")
        th.start()
        self._refresher_thread = th

    def close(self) -> None:
        """Stop the background refresher thread."""
        try:
            self._stop_event.set()
        except Exception:
            pass

    def get_calendar_list(self) -> dict[str, Any]:
        return self._execute(self.service.calendarList().list())

    def list_events(
        self,
        *,
        calendar_id: str = "primary",
        time_min: str | None = None,
        time_max: str | None = None,
        max_results: int = 250,
        single_events: bool = True,
        order_by: str | None = "startTime",
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "calendarId": calendar_id,
            "maxResults": max_results,
            "singleEvents": single_events,
        }
        if time_min:
            params["timeMin"] = time_min
        if time_max:
            params["timeMax"] = time_max
        if order_by:
            params["orderBy"] = order_by
        return self._execute(self.service.events().list(**params))
