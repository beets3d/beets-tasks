import json
import time
from datetime import date, datetime, timedelta
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .google_sheets_client import GoogleSheetsClient, GoogleSheetsClientError
from .jira_client import JiraClient, JiraClientError, JiraForbiddenProjectError
from .models import AccessLog
from .waha_client import WahaClient, WahaClientError


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
            "description": "Get one issue by key from allowed projects.",
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
            "name": "jira_update_issue",
            "description": "Update issue fields for one issue in allowed projects.",
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
            "description": "Add a comment to one issue in allowed projects.",
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

    if name == "jira_update_issue":
        issue_key = arguments.get("issueKey", "")
        fields = arguments.get("fields", {})
        return client.update_issue(issue_key=issue_key, fields=fields)

    if name == "jira_add_comment":
        issue_key = arguments.get("issueKey", "")
        comment = arguments.get("comment", "")
        return client.add_comment(issue_key=issue_key, comment=comment)

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
            message="ok" if response.status_code < 400 else "error",
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
        message=json.loads(response.content.decode("utf-8")).get("error", {}).get("message", "error"),
    )
    return response
