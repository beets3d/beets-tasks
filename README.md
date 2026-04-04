# Beets Tasks MCP Access

This project exposes a JSON-RPC MCP gateway for Jira operations with project-level access control.

## Base URL

- Production (current): `http://tasks.beets3d.cn:8001`
- Local: `http://127.0.0.1:8001`

## Endpoints

- Health check: `GET /healthz`
- MCP endpoint: `POST /mcp`

## Authentication

If `MCP_API_KEY` is configured on the server, every `POST /mcp` request must include:

- Header: `X-API-Key: <your-shared-key>`

Optional headers used for access logs:

- `X-Actor: <user-or-system-name>`

## Protocol

The gateway accepts JSON-RPC 2.0 requests.

Supported methods:

- `initialize`
- `tools/list`
- `tools/call`

## Quick Examples

### 1) Initialize

```bash
curl -X POST 'http://tasks.beets3d.cn:8001/mcp' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: YOUR_MCP_API_KEY' \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
      "clientInfo": {"name": "demo-client", "version": "1.0.0"}
    }
  }'
```

### 2) List tools

```bash
curl -X POST 'http://tasks.beets3d.cn:8001/mcp' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: YOUR_MCP_API_KEY' \
  -d '{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list",
    "params": {}
  }'
```

### 3) Call a tool

```bash
curl -X POST 'http://tasks.beets3d.cn:8001/mcp' \
  -H 'Content-Type: application/json' \
  -H 'X-API-Key: YOUR_MCP_API_KEY' \
  -H 'X-Actor: ops-bot' \
  -d '{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
      "name": "jira_search_issues",
      "arguments": {
        "jql": "statusCategory != Done ORDER BY updated DESC",
        "maxResults": 20
      }
    }
  }'
```

## Available MCP Tools

### `jira_list_allowed_projects`

Input:

```json
{}
```

### `jira_search_issues`

Input:

```json
{
  "jql": "statusCategory != Done",
  "maxResults": 20,
  "fields": ["summary", "status", "assignee", "updated"]
}
```

Notes:

- Server automatically restricts search to `ALLOWED_PROJECT_KEYS`.
- `maxResults` is clamped to `1..100`.

### `jira_get_issue`

Input:

```json
{
  "issueKey": "SL-123",
  "fields": ["summary", "status", "description"]
}
```

### `jira_get_comments`

Input:

```json
{
  "issueKey": "SL-123",
  "maxResults": 20
}
```

Notes:

- Read Jira comments (READ)

### `jira_update_issue`

Input:

```json
{
  "issueKey": "SL-123",
  "fields": {
    "summary": "Updated by MCP"
  }
}
```

### `jira_add_comment`

Input:

```json
{
  "issueKey": "SL-123",
  "comment": "This was added from MCP gateway."
}
```

Notes:

- Add Jira comment (WRITE)

### `waha_list_recent_chats`

Input:

```json
{
  "limit": 20
}
```

### `waha_get_chat_messages`

Input:

```json
{
  "chatId": "85260780428@c.us",
  "limit": 50,
  "before": "2026-03-29T09:00:00Z"
}
```

### `waha_search_messages`

Input:

```json
{
  "query": "hello",
  "limit": 50
}
```

### `waha_get_messages_in_window`

Input:

```json
{
  "hours": 24,
  "chatId": "85260780428@c.us",
  "limit": 100
}
```

Or explicit time range:

```json
{
  "startTime": "2026-03-29T00:00:00Z",
  "endTime": "2026-03-29T12:00:00Z",
  "limit": 100
}
```

### `waha_get_user_messages_recent_days`

Input:

```json
{
  "days": 7,
  "keyword": "course",
  "chatId": "85260780428@c.us",
  "limit": 100
}
```

Notes:

- Always filters `role = User`
- `keyword` and `chatId` are optional

### `google_sheets_get_spreadsheet`

Input:

```json
{
  "spreadsheetId": "your-spreadsheet-id"
}
```

### `google_sheets_get_values`

Input:

```json
{
  "spreadsheetId": "your-spreadsheet-id",
  "range": "Sheet1!A1:C20"
}
```

### `google_sheets_update_values`

Input:

```json
{
  "spreadsheetId": "your-spreadsheet-id",
  "range": "Sheet1!A1:C2",
  "values": [
    ["Name", "Status", "Owner"],
    ["Demo", "Open", "Kevin"]
  ]
}
```

### `google_sheets_append_values`

Input:

```json
{
  "spreadsheetId": "your-spreadsheet-id",
  "range": "Sheet1!A:C",
  "values": [
    ["New row", "Queued", "Bot"]
  ]
}
```

### `openclaw_sheets_list_tabs`

Input:

```json
{}
```

Notes:

- Reads from `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID`

### `openclaw_sheets_read_range`

Input:

```json
{
  "range": "Registered_Courses!A1:F20"
}
```

Notes:

- Reads from `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID`

### `openclaw_sheets_find_by_jira_id`

Input:

```json
{
  "jiraId": "SL-1444"
}
```

Optional input:

```json
{
  "jiraId": "SL-1444",
  "range": "Registered_Courses!A:Z",
  "searchColumn": "Jira ID"
}
```

Notes:

- Reads from `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID`
- Returns `count` and `matches` (header-keyed row objects)

### `openclaw_sheets_find_by_customer`

Input:

```json
{
  "customer": "10botics"
}
```

Optional input:

```json
{
  "customer": "Baptist",
  "range": "Registered_Courses!A:Z",
  "searchColumn": "Customer",
  "matchMode": "contains",
  "limit": 20
}
```

Notes:

- Reads from `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID`
- `matchMode` supports `contains` (default) and `exact`
- Returns `count` and `matches` (header-keyed row objects)

### `openclaw_sheets_find_expiring_courses`

Input:

```json
{
  "daysAhead": 30
}
```

Optional input:

```json
{
  "daysAhead": 45,
  "includeExpired": false,
  "range": "Registered_Courses!A:Z",
  "expiryColumn": "Expiry Date",
  "limit": 200
}
```

Notes:

- Reads from `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID`
- Returns rows with `_expiryDateISO` and `_daysUntilExpiry`
- Includes `unparsedDates` for source values that failed date parsing

## Response Shape

Success responses are JSON-RPC `result` objects.

For `tools/call`, tool output is returned as MCP text content:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{ ... tool result as pretty JSON string ... }"
      }
    ]
  }
}
```

Error responses use JSON-RPC `error`:

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "error": {
    "code": -32000,
    "message": "..."
  }
}
```

Common error cases:

- `401` HTTP: missing/invalid `X-API-Key`
- `-32601`: unknown JSON-RPC method
- `-32000`: Jira client or validation error
- `-32003`: project not allowed

## Server Configuration

Quick start:

1. Copy `.env.example` to `.env`
2. Fill real credentials and secrets in `.env`
3. Keep `.env` out of source control (already ignored by `.gitignore`)

Required environment variables:

- `JIRA_BASE_URL` (normally `https://api.atlassian.com`)
- `JIRA_CLOUD_ID`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `ALLOWED_PROJECT_KEYS` (comma-separated, e.g. `SL,EXCO`)
- `MCP_API_KEY` (shared key for clients)

WAHA read access variables (for `waha_*` tools):

- `WAHA_DB_HOST`
- `WAHA_DB_PORT`
- `WAHA_DB_NAME`
- `WAHA_DB_USER`
- `WAHA_DB_PASSWORD`
- `WAHA_DB_SSLMODE`

Google Sheets variables (for `google_sheets_*` tools):

- `GOOGLE_SHEETS_PROJECT_ID`
- `GOOGLE_SHEETS_CLIENT_ID`
- `GOOGLE_SHEETS_CLIENT_SECRET`
- `GOOGLE_SHEETS_AUTH_URI`
- `GOOGLE_SHEETS_TOKEN_URI`
- `GOOGLE_SHEETS_AUTH_PROVIDER_CERT_URL`
- `GOOGLE_SHEETS_REDIRECT_URI`
- `GOOGLE_SHEETS_REFRESH_TOKEN`
- `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID`
- `GOOGLE_SHEETS_SCOPES`
- `GOOGLE_CALENDAR_SCOPES`

QuickBooks variables:

- `QUICKBOOKS_CLIENT_ID`
- `QUICKBOOKS_CLIENT_SECRET`
- `QUICKBOOKS_ENVIRONMENT` (`sandbox` or `production`)
- `QUICKBOOKS_REDIRECT_URI`
- `QUICKBOOKS_REFRESH_TOKEN`
- `QUICKBOOKS_REALM_ID`

QuickBooks token bootstrap:

- Run `python3 scripts/get_quickbooks_refresh_token.py --listen --write-env` to launch OAuth, capture callback, and write `QUICKBOOKS_REFRESH_TOKEN` plus `QUICKBOOKS_REALM_ID` into `.env`.

OpenClaw-specific notes:

- `openclaw_sheets_*` tools use `GOOGLE_SHEETS_DEFAULT_SPREADSHEET_ID` so clients do not need to pass `spreadsheetId` each call.

Notes:

- The provided Google OAuth client is an installed-app credential, so you still need a valid `GOOGLE_SHEETS_REFRESH_TOKEN` before read or write calls can succeed.

Also set:

- `DJANGO_ALLOWED_HOSTS` to include your domain(s), e.g. `tasks.beets3d.cn`.

## Logging

Each MCP request is written to `mcp_gateway_accesslog` (Django model `AccessLog`) with:

- method, tool name, actor, client name
- request IP
- success/failure, status code, duration
- message
