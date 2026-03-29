import json
import time
from typing import Any

from django.conf import settings
from django.http import HttpRequest, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from .jira_client import JiraClient, JiraClientError, JiraForbiddenProjectError
from .models import AccessLog
from .waha_client import WahaClient, WahaClientError


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
