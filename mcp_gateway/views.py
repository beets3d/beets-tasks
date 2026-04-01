import json
import time
from datetime import date, datetime, timedelta
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .google_sheets_client import GoogleSheetsClient, GoogleSheetsClientError
from .google_calendar_client import GoogleCalendarClient, GoogleCalendarClientError
from .jira_client import JiraClient, JiraClientError, JiraForbiddenProjectError
from .models import AccessLog
from .waha_client import WahaClient, WahaClientError
from crm.models import Customer


def _parse_sheet_date(raw: str) -> date | None:
    value = (raw or "").strip()
    if not value:
        return None

    compact = value.replace(" ", "")
    fmts = [
        "%d%b%Y",   # 28Apr2026
        "%d%B%Y",   # 28April2026
        "%d %b %Y", # 9 Oct 2025
        "%d %B %Y", # 9 October 2025
        "%d/%m/%Y", # 10/9/2026 (dd/mm/yyyy)
        "%m/%d/%Y", # 10/9/2026 (mm/dd/yyyy)
        "%Y-%m-%d", # 2026-09-10
    ]
    for fmt in fmts:
        try:
            if fmt in {"%d%b%Y", "%d%B%Y"}:
                return datetime.strptime(compact, fmt).date()
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def _jsonrpc_result(rid: Any, result: dict[str, Any]) -> JsonResponse:
    return JsonResponse({"jsonrpc": "2.0", "id": rid, "result": result})


def _jsonrpc_error(rid: Any, code: int, message: str, data: Any = None, status: int = 200) -> JsonResponse:
    body: dict[str, Any] = {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}
    if data is not None:
        body["error"]["data"] = data
    return JsonResponse(body, status=status)


def _text_content(payload: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2)}]}


def _ensure_auth(request: HttpRequest) -> bool:
    if not settings.MCP_API_KEY:
        return True
    return request.headers.get("X-API-Key", "") == settings.MCP_API_KEY


def _extract_request_ip(request: HttpRequest) -> str | None:
    forwarded_for = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if forwarded_for:
        return forwarded_for
    return request.META.get("REMOTE_ADDR")


def _log_access(
    *,
    request: HttpRequest,
    method: str,
    tool_name: str,
    actor: str,
    client_name: str,
    project_keys: str,
    issue_key: str,
    success: bool,
    status_code: int,
    duration_ms: int,
    message: str,
) -> None:
    AccessLog.objects.create(
        client_name=client_name,
        actor=actor,
        method=method,
        tool_name=tool_name,
        request_ip=_extract_request_ip(request),
        project_keys=project_keys,
        issue_key=issue_key,
        success=success,
        status_code=status_code,
        duration_ms=duration_ms,
        message=message,
    )


READ_TOOLS = {
    "jira_list_allowed_projects",
    "jira_search_issues",
    "jira_get_issue",
    "jira_get_comments",
    "waha_list_recent_chats",
    "waha_get_chat_messages",
    "waha_search_messages",
    "waha_get_messages_in_window",
    "waha_get_user_messages_recent_days",
    "google_sheets_get_spreadsheet",
    "google_sheets_get_values",
    "openclaw_sheets_list_tabs",
    "openclaw_sheets_read_range",
    "openclaw_sheets_find_by_jira_id",
    "openclaw_sheets_find_by_customer",
    "openclaw_sheets_find_expiring_courses",
    "crm_list_customers",
    "crm_get_customer",
}

WRITE_TOOLS = {
    "jira_update_issue",
    "jira_add_comment",
    "google_sheets_update_values",
    "google_sheets_append_values",
    "crm_update_customer",
}


def _tool_access_type(method: str, tool_name: str) -> str:
    if method != "tools/call":
        return "core"
    if tool_name in WRITE_TOOLS:
        return "write"
    if tool_name in READ_TOOLS:
        return "read"
    return "unknown"


def _build_log_message(
    *,
    access_type: str,
    method: str,
    tool_name: str,
    issue_key: str,
    success: bool,
    error_message: str = "",
) -> str:
    status = "ok" if success else "error"
    target = f" issue={issue_key}" if issue_key else ""
    action = tool_name or method
    base = f"{access_type}:{action}{target}:{status}"
    if not success and error_message:
        return f"{base}:{error_message}"
    return base


def _tools_description() -> list[dict[str, Any]]:
    return [
        {
            "name": "jira_list_allowed_projects",
            "description": "List projects that OpenClaw is allowed to access.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "jira_search_issues",
            "description": "Search Jira issues only inside allowed projects.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "jql": {"type": "string"},
                    "maxResults": {"type": "integer", "minimum": 1, "maximum": 100},
                    "fields": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "jira_get_issue",
            "description": "[READ] Get one issue by key from allowed projects.",
            "accessType": "read",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string"},
                    "fields": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["issueKey"],
                "additionalProperties": False,
            },
        },
        {
            "name": "jira_get_comments",
            "description": "[READ] Read comments for one issue in allowed projects.",
            "accessType": "read",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string"},
                    "maxResults": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "required": ["issueKey"],
                "additionalProperties": False,
            },
        },
        {
            "name": "jira_update_issue",
            "description": "[WRITE] Update issue fields for one issue in allowed projects.",
            "accessType": "write",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string"},
                    "fields": {"type": "object"},
                },
                "required": ["issueKey", "fields"],
                "additionalProperties": False,
            },
        },
        {
            "name": "jira_add_comment",
            "description": "[WRITE] Add a comment to one issue in allowed projects.",
            "accessType": "write",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": ["issueKey", "comment"],
                "additionalProperties": False,
            },
        },
        {
            "name": "jira_create_issue_link",
            "description": "[WRITE] Create a link between two Jira issues (issueLink).",
            "accessType": "write",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "sourceIssue": {"type": "string"},
                    "targetIssue": {"type": "string"},
                    "linkType": {"type": "string"},
                    "comment": {"type": "string"},
                },
                "required": ["sourceIssue", "targetIssue"],
                "additionalProperties": False,
            },
        },
        {
            "name": "jira_create_remote_link",
            "description": "[WRITE] Attach an external URL (remote link) to a Jira issue.",
            "accessType": "write",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "issueKey": {"type": "string"},
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["issueKey", "url"],
                "additionalProperties": False,
            },
        },
        {
            "name": "waha_list_recent_chats",
            "description": "List WhatsApp chats ordered by latest message time from WAHA message store.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "minimum": 1, "maximum": 100},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "waha_get_chat_messages",
            "description": "Get messages for a chat from WAHA message store.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "chatId": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                    "before": {"type": "string", "description": "ISO timestamp; return messages before this value."},
                },
                "required": ["chatId"],
                "additionalProperties": False,
            },
        },
        {
            "name": "waha_search_messages",
            "description": "Search WhatsApp messages by content keyword.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
        {
            "name": "waha_get_messages_in_window",
            "description": "Get WhatsApp messages in a time window. Use hours or startTime/endTime.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "minimum": 1, "maximum": 720},
                    "startTime": {"type": "string", "description": "ISO datetime, e.g. 2026-03-29T08:00:00Z"},
                    "endTime": {"type": "string", "description": "ISO datetime, e.g. 2026-03-29T10:00:00Z"},
                    "chatId": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "waha_get_user_messages_recent_days",
            "description": "Get User-role messages from recent N days with optional keyword and chat filter.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "minimum": 1, "maximum": 90},
                    "keyword": {"type": "string"},
                    "chatId": {"type": "string"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "required": ["days"],
                "additionalProperties": False,
            },
        },
        {
            "name": "google_sheets_get_spreadsheet",
            "description": "Get spreadsheet metadata and sheet list from Google Sheets.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "ranges": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "google_sheets_get_values",
            "description": "Read values from a Google Sheets range.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "range": {"type": "string"},
                    "majorDimension": {"type": "string", "enum": ["ROWS", "COLUMNS"]},
                },
                "required": ["range"],
                "additionalProperties": False,
            },
        },
        {
            "name": "google_sheets_update_values",
            "description": "Overwrite values in a Google Sheets range.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "range": {"type": "string"},
                    "values": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {},
                        },
                    },
                    "valueInputOption": {"type": "string", "enum": ["RAW", "USER_ENTERED"]},
                },
                "required": ["range", "values"],
                "additionalProperties": False,
            },
        },
        {
            "name": "google_sheets_append_values",
            "description": "Append rows to a Google Sheets range.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "spreadsheetId": {"type": "string"},
                    "range": {"type": "string"},
                    "values": {
                        "type": "array",
                        "items": {
                            "type": "array",
                            "items": {},
                        },
                    },
                    "valueInputOption": {"type": "string", "enum": ["RAW", "USER_ENTERED"]},
                    "insertDataOption": {"type": "string", "enum": ["OVERWRITE", "INSERT_ROWS"]},
                },
                "required": ["range", "values"],
                "additionalProperties": False,
            },
        },
        {
            "name": "google_calendar_list",
            "description": "List calendars available to the service account / token.",
            "accessType": "read",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "google_calendar_list_events",
            "description": "List events from a calendar.",
            "accessType": "read",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "calendarId": {"type": "string"},
                    "timeMin": {"type": "string"},
                    "timeMax": {"type": "string"},
                    "maxResults": {"type": "integer", "minimum": 1, "maximum": 250},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "google_calendar_list_events_filtered",
            "description": "List events filtered by date (or start/end) and person (attendee email or name).",
            "accessType": "read",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "calendarId": {"type": "string"},
                    "date": {"type": "string", "description": "ISO date YYYY-MM-DD (returns events for that day)"},
                    "timeMin": {"type": "string"},
                    "timeMax": {"type": "string"},
                    "person": {"type": "string", "description": "email or display name to filter attendees"},
                    "maxResults": {"type": "integer", "minimum": 1, "maximum": 250},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "openclaw_sheets_list_tabs",
            "description": "List tabs from the default OpenClaw Google Sheet configured in env.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
        {
            "name": "openclaw_sheets_read_range",
            "description": "Read a range from the default OpenClaw Google Sheet configured in env.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "range": {"type": "string"},
                    "majorDimension": {"type": "string", "enum": ["ROWS", "COLUMNS"]},
                },
                "required": ["range"],
                "additionalProperties": False,
            },
        },
        {
            "name": "openclaw_sheets_find_by_jira_id",
            "description": "Find rows by Jira ID from the default OpenClaw Google Sheet.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "jiraId": {"type": "string"},
                    "range": {"type": "string", "description": "Optional range, default Registered_Courses!A:Z"},
                    "searchColumn": {"type": "string", "description": "Header name to match Jira ID, default Jira ID"},
                },
                "required": ["jiraId"],
                "additionalProperties": False,
            },
        },
        {
            "name": "openclaw_sheets_find_by_customer",
            "description": "Find rows by customer name from the default OpenClaw Google Sheet.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "customer": {"type": "string"},
                    "range": {"type": "string", "description": "Optional range, default Registered_Courses!A:Z"},
                    "searchColumn": {"type": "string", "description": "Header name to match customer, default Customer"},
                    "matchMode": {"type": "string", "enum": ["contains", "exact"]},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 200},
                },
                "required": ["customer"],
                "additionalProperties": False,
            },
        },
        {
            "name": "openclaw_sheets_find_expiring_courses",
            "description": "Find courses with expiry date within a future window from the default OpenClaw Google Sheet.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "daysAhead": {"type": "integer", "minimum": 1, "maximum": 365},
                    "includeExpired": {"type": "boolean"},
                    "range": {"type": "string", "description": "Optional range, default Registered_Courses!A:Z"},
                    "expiryColumn": {"type": "string", "description": "Header name for expiry date, default Expiry Date"},
                    "limit": {"type": "integer", "minimum": 1, "maximum": 500},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "crm_list_customers",
                "description": "List customers from CRM with optional filters (search, type, important).",
                "accessType": "read",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "search text for name, company or email"},
                        "customerType": {"type": "string"},
                        "important": {"type": "boolean"},
                        "limit": {"type": "integer", "minimum": 1, "maximum": 1000},
                        "offset": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
            },
            {
                "name": "crm_get_customer",
                "description": "Get one customer by id.",
                "accessType": "read",
                "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"], "additionalProperties": False},
            },
            {
                "name": "crm_update_customer",
                "description": "Update fields on one customer by id.",
                "accessType": "write",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "fields": {"type": "object"},
                    },
                    "required": ["id", "fields"],
                    "additionalProperties": False,
                }
            }
        ]


def _handle_tool_call(name: str, arguments: dict[str, Any], client: JiraClient) -> dict[str, Any]:
    if name == "jira_list_allowed_projects":
        return {"allowedProjects": sorted(client.allowed_projects)}

    if name == "jira_search_issues":
        result = client.search_issues(
            jql=arguments.get("jql"),
            max_results=arguments.get("maxResults", 20),
            fields=arguments.get("fields"),
        )
        return {
            "total": result.get("total", 0),
            "issues": result.get("issues", []),
        }

    if name == "jira_get_issue":
        issue_key = arguments.get("issueKey", "")
        return client.get_issue(issue_key=issue_key, fields=arguments.get("fields"))

    if name == "jira_get_comments":
        issue_key = arguments.get("issueKey", "")
        return client.get_comments(issue_key=issue_key, max_results=arguments.get("maxResults", 20))

    if name == "jira_update_issue":
        issue_key = arguments.get("issueKey", "")
        fields = arguments.get("fields", {})
        return client.update_issue(issue_key=issue_key, fields=fields)

    if name == "jira_add_comment":
        issue_key = arguments.get("issueKey", "")
        comment = arguments.get("comment", "")
        return client.add_comment(issue_key=issue_key, comment=comment)

    if name == "jira_create_issue_link":
        source = str(arguments.get("sourceIssue", "") or "").strip()
        target = str(arguments.get("targetIssue", "") or "").strip()
        link_type = str(arguments.get("linkType", "Relates") or "Relates").strip()
        comment = arguments.get("comment")
        if not source or not target:
            raise JiraClientError("sourceIssue and targetIssue are required")
        return client.create_issue_link(source_issue=source, target_issue=target, link_type=link_type, comment=comment)

    if name == "jira_create_remote_link":
        issue_key = str(arguments.get("issueKey", "") or "").strip()
        url = str(arguments.get("url", "") or "").strip()
        title = arguments.get("title")
        summary = arguments.get("summary")
        if not issue_key or not url:
            raise JiraClientError("issueKey and url are required")
        return client.create_remote_link(issue_key=issue_key, url=url, title=title, summary=summary)

    if name == "waha_list_recent_chats":
        waha = WahaClient()
        return {"chats": waha.list_recent_chats(limit=arguments.get("limit", 20))}

    if name == "waha_get_chat_messages":
        waha = WahaClient()
        return waha.get_chat_messages(
            chat_id=arguments.get("chatId", ""),
            limit=arguments.get("limit", 50),
            before=arguments.get("before"),
        )

    if name == "waha_search_messages":
        waha = WahaClient()
        return {
            "matches": waha.search_messages(
                query=arguments.get("query", ""),
                limit=arguments.get("limit", 50),
            )
        }

    if name == "waha_get_messages_in_window":
        waha = WahaClient()
        return waha.get_messages_in_window(
            start_time=arguments.get("startTime"),
            end_time=arguments.get("endTime"),
            hours=arguments.get("hours"),
            chat_id=arguments.get("chatId"),
            limit=arguments.get("limit", 100),
        )

    if name == "waha_get_user_messages_recent_days":
        waha = WahaClient()
        return waha.get_user_messages_recent_days(
            days=arguments.get("days"),
            keyword=arguments.get("keyword"),
            chat_id=arguments.get("chatId"),
            limit=arguments.get("limit", 100),
        )

    if name == "google_sheets_get_spreadsheet":
        sheets = GoogleSheetsClient()
        return sheets.get_spreadsheet(
            spreadsheet_id=arguments.get("spreadsheetId"),
            ranges=arguments.get("ranges"),
        )

    if name == "google_sheets_get_values":
        sheets = GoogleSheetsClient()
        return sheets.get_values(
            spreadsheet_id=arguments.get("spreadsheetId"),
            range_name=arguments.get("range", ""),
            major_dimension=arguments.get("majorDimension"),
        )

    if name == "google_sheets_update_values":
        sheets = GoogleSheetsClient()
        return sheets.update_values(
            spreadsheet_id=arguments.get("spreadsheetId"),
            range_name=arguments.get("range", ""),
            values=arguments.get("values", []),
            value_input_option=arguments.get("valueInputOption", "USER_ENTERED"),
        )

    if name == "google_sheets_append_values":
        sheets = GoogleSheetsClient()
        return sheets.append_values(
            spreadsheet_id=arguments.get("spreadsheetId"),
            range_name=arguments.get("range", ""),
            values=arguments.get("values", []),
            value_input_option=arguments.get("valueInputOption", "USER_ENTERED"),
            insert_data_option=arguments.get("insertDataOption", "INSERT_ROWS"),
        )

    if name == "google_calendar_list":
        gc = GoogleCalendarClient()
        return gc.get_calendar_list()

    if name == "google_calendar_list_events":
        gc = GoogleCalendarClient()
        return gc.list_events(
            calendar_id=arguments.get("calendarId", "primary"),
            time_min=arguments.get("timeMin"),
            time_max=arguments.get("timeMax"),
            max_results=arguments.get("maxResults", 250),
            single_events=arguments.get("singleEvents", True),
            order_by=arguments.get("orderBy", "startTime"),
        )

    if name == "google_calendar_list_events_filtered":
        gc = GoogleCalendarClient()
        cal_id = arguments.get("calendarId", "primary")
        person = (arguments.get("person") or "").strip()
        date_arg = (arguments.get("date") or "").strip()
        time_min = arguments.get("timeMin")
        time_max = arguments.get("timeMax")
        max_results = int(arguments.get("maxResults", 250))

        # If date is provided, construct a full-day range in UTC
        if date_arg and not (time_min or time_max):
            try:
                from datetime import datetime, timedelta

                d = datetime.strptime(date_arg, "%Y-%m-%d")
                time_min = d.strftime("%Y-%m-%dT00:00:00Z")
                time_max = (d + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00Z")
            except Exception:
                # ignore parse errors and fall back to provided timeMin/timeMax
                pass

        payload = gc.list_events(
            calendar_id=cal_id,
            time_min=time_min,
            time_max=time_max,
            max_results=max_results,
            single_events=True,
            order_by="startTime",
        )

        events = payload.get("items", []) if isinstance(payload, dict) else []
        if person:
            person_lower = person.lower()
            filtered = []
            for ev in events:
                matched = False
                # check attendees
                for a in ev.get("attendees", []) or []:
                    email = (a.get("email") or "").lower()
                    name = (a.get("displayName") or "").lower()
                    if person_lower in email or person_lower in name:
                        matched = True
                        break
                # check organizer if not matched
                if not matched:
                    org = ev.get("organizer", {}) or {}
                    if person_lower in (org.get("email", "") or "").lower() or person_lower in (org.get("displayName", "") or "").lower():
                        matched = True
                if matched:
                    filtered.append(ev)
            events = filtered

        return {"count": len(events), "items": events}

    if name == "openclaw_sheets_list_tabs":
        sheets = GoogleSheetsClient()
        payload = sheets.get_spreadsheet()
        tabs: list[dict[str, Any]] = []
        for sheet in payload.get("sheets", []):
            props = sheet.get("properties", {})
            tabs.append(
                {
                    "sheetId": props.get("sheetId"),
                    "title": props.get("title"),
                    "index": props.get("index"),
                }
            )
        return {
            "spreadsheetId": payload.get("spreadsheetId"),
            "title": payload.get("properties", {}).get("title"),
            "tabs": tabs,
        }

    if name == "openclaw_sheets_read_range":
        sheets = GoogleSheetsClient()
        return sheets.get_values(
            range_name=arguments.get("range", ""),
            major_dimension=arguments.get("majorDimension"),
        )

    if name == "openclaw_sheets_find_by_jira_id":
        jira_id = str(arguments.get("jiraId", "")).strip()
        if not jira_id:
            raise GoogleSheetsClientError("jiraId is required")

        range_name = str(arguments.get("range", "") or "Registered_Courses!A:Z")
        search_column = str(arguments.get("searchColumn", "") or "Jira ID")

        sheets = GoogleSheetsClient()
        payload = sheets.get_values(range_name=range_name, major_dimension="ROWS")
        rows = payload.get("values", [])
        if not rows:
            return {
                "jiraId": jira_id,
                "range": range_name,
                "searchColumn": search_column,
                "count": 0,
                "matches": [],
            }

        headers = [str(col).strip() for col in rows[0]]
        try:
            search_index = headers.index(search_column)
        except ValueError as exc:
            raise GoogleSheetsClientError(f"searchColumn not found in header: {search_column}") from exc

        target = jira_id.upper()
        matches: list[dict[str, Any]] = []
        for row in rows[1:]:
            if search_index >= len(row):
                continue
            cell = str(row[search_index]).strip().upper()
            if cell != target:
                continue
            row_obj: dict[str, Any] = {}
            for i, header in enumerate(headers):
                if not header:
                    continue
                row_obj[header] = row[i] if i < len(row) else ""
            matches.append(row_obj)

        return {
            "jiraId": jira_id,
            "range": range_name,
            "searchColumn": search_column,
            "count": len(matches),
            "matches": matches,
        }

    if name == "openclaw_sheets_find_by_customer":
        customer = str(arguments.get("customer", "")).strip()
        if not customer:
            raise GoogleSheetsClientError("customer is required")

        range_name = str(arguments.get("range", "") or "Registered_Courses!A:Z")
        search_column = str(arguments.get("searchColumn", "") or "Customer")
        match_mode = str(arguments.get("matchMode", "") or "contains").lower()
        if match_mode not in {"contains", "exact"}:
            raise GoogleSheetsClientError("matchMode must be one of: contains, exact")
        limit = max(1, min(int(arguments.get("limit", 50)), 200))

        sheets = GoogleSheetsClient()
        payload = sheets.get_values(range_name=range_name, major_dimension="ROWS")
        rows = payload.get("values", [])
        if not rows:
            return {
                "customer": customer,
                "range": range_name,
                "searchColumn": search_column,
                "matchMode": match_mode,
                "count": 0,
                "matches": [],
            }

        headers = [str(col).strip() for col in rows[0]]
        try:
            search_index = headers.index(search_column)
        except ValueError as exc:
            raise GoogleSheetsClientError(f"searchColumn not found in header: {search_column}") from exc

        target = customer.upper()
        matches: list[dict[str, Any]] = []
        for row in rows[1:]:
            if search_index >= len(row):
                continue
            cell = str(row[search_index]).strip()
            cell_upper = cell.upper()
            is_match = (cell_upper == target) if match_mode == "exact" else (target in cell_upper)
            if not is_match:
                continue

            row_obj: dict[str, Any] = {}
            for i, header in enumerate(headers):
                if not header:
                    continue
                row_obj[header] = row[i] if i < len(row) else ""
            matches.append(row_obj)
            if len(matches) >= limit:
                break

        return {
            "customer": customer,
            "range": range_name,
            "searchColumn": search_column,
            "matchMode": match_mode,
            "count": len(matches),
            "matches": matches,
        }

    if name == "openclaw_sheets_find_expiring_courses":
        days_ahead = max(1, min(int(arguments.get("daysAhead", 30)), 365))
        include_expired = bool(arguments.get("includeExpired", False))
        range_name = str(arguments.get("range", "") or "Registered_Courses!A:Z")
        expiry_column = str(arguments.get("expiryColumn", "") or "Expiry Date")
        limit = max(1, min(int(arguments.get("limit", 200)), 500))

        sheets = GoogleSheetsClient()
        payload = sheets.get_values(range_name=range_name, major_dimension="ROWS")
        rows = payload.get("values", [])
        if not rows:
            return {
                "daysAhead": days_ahead,
                "includeExpired": include_expired,
                "range": range_name,
                "expiryColumn": expiry_column,
                "count": 0,
                "matches": [],
                "unparsedDates": [],
            }

        headers = [str(col).strip() for col in rows[0]]
        try:
            expiry_index = headers.index(expiry_column)
        except ValueError as exc:
            raise GoogleSheetsClientError(f"expiryColumn not found in header: {expiry_column}") from exc

        today = date.today()
        end_date = today + timedelta(days=days_ahead)

        matches: list[dict[str, Any]] = []
        unparsed: list[str] = []

        for row in rows[1:]:
            if expiry_index >= len(row):
                continue

            expiry_raw = str(row[expiry_index]).strip()
            if not expiry_raw:
                continue

            expiry_date = _parse_sheet_date(expiry_raw)
            if expiry_date is None:
                if expiry_raw not in unparsed:
                    unparsed.append(expiry_raw)
                continue

            if include_expired:
                in_window = expiry_date <= end_date
            else:
                in_window = today <= expiry_date <= end_date
            if not in_window:
                continue

            row_obj: dict[str, Any] = {}
            for i, header in enumerate(headers):
                if not header:
                    continue
                row_obj[header] = row[i] if i < len(row) else ""
            row_obj["_expiryDateISO"] = expiry_date.isoformat()
            row_obj["_daysUntilExpiry"] = (expiry_date - today).days
            matches.append(row_obj)

        matches.sort(key=lambda x: x.get("_daysUntilExpiry", 999999))
        matches = matches[:limit]

        return {
            "daysAhead": days_ahead,
            "includeExpired": include_expired,
            "range": range_name,
            "expiryColumn": expiry_column,
            "today": today.isoformat(),
            "windowEnd": end_date.isoformat(),
            "count": len(matches),
            "matches": matches,
            "unparsedDates": unparsed,
        }

    if name == "crm_list_customers":
        query_text = str(arguments.get("query", "") or "").strip()
        ctype = arguments.get("customerType")
        important = arguments.get("important")
        limit = max(1, min(int(arguments.get("limit", 100)), 1000))
        offset = max(0, int(arguments.get("offset", 0)))

        qs = Customer.objects.all()
        # ctype may be an id or a key string
        if ctype:
            try:
                cid_val = int(ctype)
            except Exception:
                cid_val = None
            if cid_val:
                qs = qs.filter(customer_type__id=cid_val)
            else:
                qs = qs.filter(customer_type__key=str(ctype))
        if important is not None:
            qs = qs.filter(important=bool(important))
        if query_text:
            from django.db.models import Q

            q = Q(name__icontains=query_text) | Q(company_name__icontains=query_text) | Q(email__icontains=query_text) | Q(external_id__icontains=query_text)
            qs = qs.filter(q)

        total = qs.count()
        items = []
        for obj in qs.order_by("-updated_at")[offset : offset + limit]:
            items.append({
                "id": obj.id,
                "name": obj.name,
                "external_id": obj.external_id,
                "website_url": obj.website_url,
                        "attn": obj.attn,
                        "fax": obj.fax,
                "street_address": obj.street_address,
                "city": obj.city,
                "state": obj.state,
                "zip_code": obj.zip_code,
                "country": obj.country,
                "company_name": obj.company_name,
                "email": obj.email,
                "phone": obj.phone,
                "mobile": obj.mobile,
                "attn_2": obj.attn_2,
                "phone_2": obj.phone_2,
                "email_2": obj.email_2,
                "attn_3": obj.attn_3,
                "phone_3": obj.phone_3,
                "email_3": obj.email_3,
                "important": obj.important,
                "customer_type": (obj.customer_type.key if getattr(obj, "customer_type", None) else None),
                "last_contact": obj.last_contact.isoformat() if obj.last_contact else None,
                "sheet_last_updated": obj.sheet_last_updated.isoformat() if obj.sheet_last_updated else None,
                "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
            })

        return {"total": total, "count": len(items), "items": items}

    if name == "crm_get_customer":
        cid = int(arguments.get("id", 0))
        if not cid:
            raise JiraClientError("id is required")
        obj = Customer.objects.filter(id=cid).first()
        if not obj:
            raise JiraClientError("customer not found")
        return {
            "id": obj.id,
            "name": obj.name,
            "external_id": obj.external_id,
            "company_name": obj.company_name,
            "street_address": obj.street_address,
            "city": obj.city,
            "state": obj.state,
            "country": obj.country,
            "zip_code": obj.zip_code,
            "email": obj.email,
            "attn": obj.attn,
            "fax": obj.fax,
            "phone": obj.phone,
            "mobile": obj.mobile,
            "attn_2": obj.attn_2,
            "phone_2": obj.phone_2,
            "email_2": obj.email_2,
            "attn_3": obj.attn_3,
            "phone_3": obj.phone_3,
            "email_3": obj.email_3,
            "website_url": obj.website_url,
            "profile": obj.profile,
            "remark": obj.remark,
            "important": obj.important,
            "customer_type": (obj.customer_type.key if getattr(obj, "customer_type", None) else None),
            "last_contact": obj.last_contact.isoformat() if obj.last_contact else None,
            "sheet_last_updated": obj.sheet_last_updated.isoformat() if obj.sheet_last_updated else None,
            "sheet_updated_by": obj.sheet_updated_by,
            "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
        }

    if name == "crm_create_customer":
        fields = arguments.get("fields", {}) or {}
        if not isinstance(fields, dict):
            raise JiraClientError("fields must be an object")

        # map common aliases
        if "type" in fields and "customer_type" not in fields:
            fields["customer_type"] = fields.get("type")
        if "url" in fields and "website_url" not in fields:
            fields["website_url"] = fields.get("url")
        if "bio" in fields and "profile" not in fields:
            fields["profile"] = fields.get("bio")
        if "address" in fields and "street_address" not in fields:
            fields["street_address"] = fields.get("address")
        if "addr" in fields and "street_address" not in fields:
            fields["street_address"] = fields.get("addr")
        if "street" in fields and "street_address" not in fields:
            fields["street_address"] = fields.get("street")

        allowed = {
            "name",
            "external_id",
            "company_name",
            "street_address",
            "city",
            "state",
            "country",
            "zip_code",
            "website_url",
            "email",
            "attn",
            "fax",
            "phone",
            "mobile",
            "attn_2",
            "phone_2",
            "email_2",
            "attn_3",
            "phone_3",
            "email_3",
            "remark",
            "important",
            "customer_type",
            "last_contact",
            "profile",
            "latitude",
            "longitude",
        }

        from crm.models import Customer as _Customer

        obj = _Customer()

        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in {"latitude", "longitude"}:
                try:
                    setattr(obj, k, float(v) if v not in (None, "") else None)
                except Exception:
                    setattr(obj, k, None)
                continue
            if k == "last_contact":
                try:
                    from django.utils.dateparse import parse_datetime

                    parsed = parse_datetime(str(v))
                    obj.last_contact = parsed
                except Exception:
                    obj.last_contact = None
            elif k == "important":
                if isinstance(v, str):
                    obj.important = str(v).strip().lower() in {"1", "true", "yes", "y", "on"}
                else:
                    obj.important = bool(v)
            elif k == "customer_type":
                if v is None or str(v).strip() == "":
                    obj.customer_type = None
                else:
                    from crm.models import CustomerType

                    ct = None
                    try:
                        cid_val = int(v)
                    except Exception:
                        cid_val = None
                    if cid_val:
                        ct = CustomerType.objects.filter(id=cid_val).first()
                    if not ct:
                        ct = CustomerType.objects.filter(key=str(v)).first()
                    if not ct:
                        ct = CustomerType.objects.create(key=str(v), label=str(v))
                    obj.customer_type = ct
            else:
                setattr(obj, k, v)

        obj.save()
        return {"id": obj.id, "created": True}
    if name == "crm_update_customer":
        cid = int(arguments.get("id", 0))
        fields = arguments.get("fields", {}) or {}
        if not cid:
            raise JiraClientError("id is required")
        if not isinstance(fields, dict):
            raise JiraClientError("fields must be an object")
        obj = Customer.objects.filter(id=cid).first()
        if not obj:
            raise JiraClientError("customer not found")

        # allow 'type' as an alias for 'customer_type'
        if "type" in fields and "customer_type" not in fields:
            fields["customer_type"] = fields.get("type")
        # allow 'url' as an alias for website_url
        if "url" in fields and "website_url" not in fields:
            fields["website_url"] = fields.get("url")
        # allow 'bio' as an alias for profile
        if "bio" in fields and "profile" not in fields:
            fields["profile"] = fields.get("bio")
        # allow common address aliases to map to 'street_address'
        if "address" in fields and "street_address" not in fields:
            fields["street_address"] = fields.get("address")
        if "addr" in fields and "street_address" not in fields:
            fields["street_address"] = fields.get("addr")
        if "street" in fields and "street_address" not in fields:
            fields["street_address"] = fields.get("street")

        allowed = {
            "name",
            "company_name",
            "street_address",
            "city",
            "state",
            "country",
            "zip_code",
            "website_url",
            "email",
            "attn",
            "fax",
            "phone",
            "mobile",
            "attn_2",
            "phone_2",
            "email_2",
            "attn_3",
            "phone_3",
            "email_3",
            "remark",
            "important",
            "customer_type",
            "last_contact",
            "profile",
            "latitude",
            "longitude",
        }

        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in {"latitude", "longitude"}:
                try:
                    setattr(obj, k, float(v) if v not in (None, "") else None)
                except Exception:
                    setattr(obj, k, None)
                continue
            if k == "last_contact":
                try:
                    from django.utils.dateparse import parse_datetime

                    parsed = parse_datetime(str(v))
                    obj.last_contact = parsed
                except Exception:
                    obj.last_contact = None
            elif k == "important":
                # coerce common truthy values to boolean
                if isinstance(v, str):
                    obj.important = str(v).strip().lower() in {"1", "true", "yes", "y", "on"}
                else:
                    obj.important = bool(v)
            elif k == "customer_type":
                # accept numeric id or key string
                if v is None or str(v).strip() == "":
                    obj.customer_type = None
                else:
                    from crm.models import CustomerType

                    ct = None
                    try:
                        cid_val = int(v)
                    except Exception:
                        cid_val = None
                    if cid_val:
                        ct = CustomerType.objects.filter(id=cid_val).first()
                    if not ct:
                        ct = CustomerType.objects.filter(key=str(v)).first()
                    if not ct:
                        # create new CustomerType if missing
                        ct = CustomerType.objects.create(key=str(v), label=str(v))
                    obj.customer_type = ct
            else:
                setattr(obj, k, v)

        obj.save()
        return {"id": obj.id, "updated": True}

    raise JiraClientError(f"Unknown tool: {name}")


@require_GET
def healthz(_: HttpRequest) -> JsonResponse:
    return JsonResponse({"ok": True})


@csrf_exempt
@require_POST
def mcp_endpoint(request: HttpRequest) -> JsonResponse:
    start = time.time()
    rid: Any = None
    method = ""
    tool_name = ""
    issue_key = ""
    access_type = "core"
    actor = request.headers.get("X-Actor", "")
    client_name = ""

    if not _ensure_auth(request):
        return JsonResponse({"error": "unauthorized"}, status=401)

    try:
        body = json.loads(request.body.decode("utf-8"))
        rid = body.get("id")
        method = body.get("method", "")
        params = body.get("params", {}) or {}

        client_info = params.get("clientInfo", {}) if isinstance(params, dict) else {}
        if isinstance(client_info, dict):
            client_name = str(client_info.get("name", ""))

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "jira-mcp-django", "version": "0.1.0"},
            }
            response = _jsonrpc_result(rid, result)

        elif method == "tools/list":
            response = _jsonrpc_result(rid, {"tools": _tools_description()})

        elif method == "tools/call":
            name = params.get("name", "")
            arguments = params.get("arguments", {})
            tool_name = str(name)
            access_type = _tool_access_type(method, tool_name)
            if not isinstance(arguments, dict):
                raise JiraClientError("Tool arguments must be an object")

            issue_key = str(arguments.get("issueKey", ""))
            jira = JiraClient()
            payload = _handle_tool_call(name=tool_name, arguments=arguments, client=jira)
            response = _jsonrpc_result(rid, _text_content(payload))

        else:
            response = _jsonrpc_error(rid, -32601, f"Method not found: {method}")

        _log_access(
            request=request,
            method=method,
            tool_name=tool_name,
            actor=actor,
            client_name=client_name,
            project_keys=",".join(sorted(settings.ALLOWED_PROJECT_KEYS)),
            issue_key=issue_key,
            success=response.status_code < 400 and "error" not in json.loads(response.content.decode("utf-8")),
            status_code=response.status_code,
            duration_ms=int((time.time() - start) * 1000),
            message=_build_log_message(
                access_type=access_type,
                method=method,
                tool_name=tool_name,
                issue_key=issue_key,
                success=response.status_code < 400 and "error" not in json.loads(response.content.decode("utf-8")),
            ),
        )
        return response

    except JiraForbiddenProjectError as exc:
        response = _jsonrpc_error(rid, -32003, str(exc))
    except JiraClientError as exc:
        response = _jsonrpc_error(rid, -32000, str(exc))
    except WahaClientError as exc:
        response = _jsonrpc_error(rid, -32010, str(exc))
    except GoogleSheetsClientError as exc:
        response = _jsonrpc_error(rid, -32020, str(exc))
    except json.JSONDecodeError:
        response = _jsonrpc_error(rid, -32700, "Invalid JSON")
    except Exception as exc:
        response = _jsonrpc_error(rid, -32603, "Internal error", data=str(exc))

    _log_access(
        request=request,
        method=method or "unknown",
        tool_name=tool_name,
        actor=actor,
        client_name=client_name,
        project_keys=",".join(sorted(settings.ALLOWED_PROJECT_KEYS)),
        issue_key=issue_key,
        success=False,
        status_code=response.status_code,
        duration_ms=int((time.time() - start) * 1000),
        message=_build_log_message(
            access_type=access_type,
            method=method or "unknown",
            tool_name=tool_name,
            issue_key=issue_key,
            success=False,
            error_message=json.loads(response.content.decode("utf-8")).get("error", {}).get("message", "error"),
        ),
    )
    return response
