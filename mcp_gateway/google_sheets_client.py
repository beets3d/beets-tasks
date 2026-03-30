from __future__ import annotations

from typing import Any

from django.conf import settings
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


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
        creds.refresh(Request())
        self.service = build("sheets", "v4", credentials=creds, cache_discovery=False)

    @staticmethod
    def _resolve_spreadsheet_id(spreadsheet_id: str | None) -> str:
        candidate = (spreadsheet_id or settings.GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID).strip()
        if not candidate:
            raise GoogleSheetsClientError("spreadsheetId is required")
        return candidate

    def _execute(self, request: Any) -> dict[str, Any]:
        try:
            result = request.execute()
        except HttpError as exc:
            raise GoogleSheetsClientError(f"Google Sheets API error: {exc}") from exc
        except Exception as exc:
            raise GoogleSheetsClientError(str(exc)) from exc
        if isinstance(result, dict):
            return result
        return {"result": result}

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