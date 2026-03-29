import re
from typing import Any

import requests
from django.conf import settings


class JiraClientError(Exception):
    pass


class JiraForbiddenProjectError(JiraClientError):
    pass


class JiraClient:
    ISSUE_KEY_RE = re.compile(r"^(?P<project>[A-Z][A-Z0-9]+)-\d+$")

    def __init__(self) -> None:
        if not settings.JIRA_CLOUD_ID:
            raise JiraClientError("JIRA_CLOUD_ID is required")
        if not settings.JIRA_EMAIL or not settings.JIRA_API_TOKEN:
            raise JiraClientError("JIRA_EMAIL and JIRA_API_TOKEN are required")
        if not settings.ALLOWED_PROJECT_KEYS:
            raise JiraClientError("ALLOWED_PROJECT_KEYS cannot be empty")

        self.base_url = f"{settings.JIRA_BASE_URL}/ex/jira/{settings.JIRA_CLOUD_ID}"
        self.session = requests.Session()
        self.session.auth = (settings.JIRA_EMAIL, settings.JIRA_API_TOKEN)
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    @property
    def allowed_projects(self) -> set[str]:
        return set(settings.ALLOWED_PROJECT_KEYS)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self.session.request(method, url, timeout=20, **kwargs)
        if resp.status_code >= 400:
            raise JiraClientError(f"Jira API error {resp.status_code}: {resp.text[:500]}")
        if not resp.content:
            return {}
        return resp.json()

    def _project_from_issue_key(self, issue_key: str) -> str:
        m = self.ISSUE_KEY_RE.match(issue_key.upper())
        if not m:
            raise JiraClientError(f"Invalid issue key: {issue_key}")
        return m.group("project")

    def ensure_issue_allowed(self, issue_key: str) -> str:
        project = self._project_from_issue_key(issue_key)
        if project not in self.allowed_projects:
            raise JiraForbiddenProjectError(
                f"Project {project} is not allowed. Allowed: {sorted(self.allowed_projects)}"
            )
        return project

    def constrain_jql(self, jql: str | None) -> str:
        allowed_clause = "project in (" + ",".join(sorted(self.allowed_projects)) + ")"
        if not jql or not jql.strip():
            return f"{allowed_clause} ORDER BY updated DESC"
        return f"{allowed_clause} AND ({jql})"

    def search_issues(self, jql: str | None, max_results: int = 20, fields: list[str] | None = None) -> dict[str, Any]:
        payload = {
            "jql": self.constrain_jql(jql),
            "maxResults": max(1, min(max_results, 100)),
            "fields": fields or ["summary", "status", "assignee", "priority", "project", "issuetype", "updated"],
        }
        return self._request("POST", "/rest/api/3/search/jql", json=payload)

    def get_issue(self, issue_key: str, fields: list[str] | None = None) -> dict[str, Any]:
        self.ensure_issue_allowed(issue_key)
        params = {}
        if fields:
            params["fields"] = ",".join(fields)
        return self._request("GET", f"/rest/api/3/issue/{issue_key}", params=params)

    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.ensure_issue_allowed(issue_key)
        if not isinstance(fields, dict) or not fields:
            raise JiraClientError("fields must be a non-empty object")
        self._request("PUT", f"/rest/api/3/issue/{issue_key}", json={"fields": fields})
        return {"updated": True, "issueKey": issue_key}

    def add_comment(self, issue_key: str, comment: str) -> dict[str, Any]:
        self.ensure_issue_allowed(issue_key)
        if not comment or not comment.strip():
            raise JiraClientError("comment cannot be empty")
        payload = {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": comment}],
                    }
                ],
            }
        }
        result = self._request("POST", f"/rest/api/3/issue/{issue_key}/comment", json=payload)
        return {"issueKey": issue_key, "commentId": result.get("id")}
