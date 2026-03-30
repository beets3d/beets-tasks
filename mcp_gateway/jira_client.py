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

    def _get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        payload = self._request("GET", f"/rest/api/3/issue/{issue_key}/transitions")
        return payload.get("transitions", [])

    def _resolve_transition_id(self, issue_key: str, status_value: Any) -> tuple[str, str]:
        target_id = ""
        target_name = ""

        if isinstance(status_value, dict):
            if status_value.get("id") is not None:
                target_id = str(status_value.get("id", "")).strip()
            elif status_value.get("name") is not None:
                target_name = str(status_value.get("name", "")).strip()
            elif isinstance(status_value.get("to"), dict):
                to_obj = status_value.get("to") or {}
                if to_obj.get("id") is not None:
                    target_id = str(to_obj.get("id", "")).strip()
                elif to_obj.get("name") is not None:
                    target_name = str(to_obj.get("name", "")).strip()
        elif status_value is not None:
            raw = str(status_value).strip()
            if raw.isdigit():
                target_id = raw
            else:
                target_name = raw

        if not target_id and not target_name:
            raise JiraClientError("status must provide transition id or name")

        transitions = self._get_transitions(issue_key)
        for t in transitions:
            tid = str(t.get("id", "")).strip()
            tname = str(t.get("name", "")).strip()
            to_name = str((t.get("to") or {}).get("name", "")).strip()
            if target_id and tid == target_id:
                return tid, to_name or tname or tid
            if target_name and target_name.lower() in {tname.lower(), to_name.lower()}:
                return tid, to_name or tname or tid

        available = [str((t.get("to") or {}).get("name") or t.get("name") or t.get("id")) for t in transitions]
        raise JiraClientError(f"No matching transition for status '{target_name or target_id}'. Available: {available}")

    def _transition_issue(self, issue_key: str, transition_id: str) -> None:
        self._request(
            "POST",
            f"/rest/api/3/issue/{issue_key}/transitions",
            json={"transition": {"id": transition_id}},
        )

    def update_issue(self, issue_key: str, fields: dict[str, Any]) -> dict[str, Any]:
        self.ensure_issue_allowed(issue_key)
        if not isinstance(fields, dict) or not fields:
            raise JiraClientError("fields must be a non-empty object")

        field_updates = dict(fields)
        status_value = field_updates.pop("status", None)

        did_field_update = False
        did_transition = False
        transitioned_to = ""

        if field_updates:
            self._request("PUT", f"/rest/api/3/issue/{issue_key}", json={"fields": field_updates})
            did_field_update = True

        if status_value is not None:
            transition_id, transition_name = self._resolve_transition_id(issue_key, status_value)
            self._transition_issue(issue_key, transition_id)
            did_transition = True
            transitioned_to = transition_name

        if not did_field_update and not did_transition:
            raise JiraClientError("fields must include at least one updatable key")

        return {
            "updated": True,
            "issueKey": issue_key,
            "fieldsUpdated": did_field_update,
            "statusTransitioned": did_transition,
            "statusTo": transitioned_to,
        }

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

    def get_comments(self, issue_key: str, max_results: int = 20) -> dict[str, Any]:
        self.ensure_issue_allowed(issue_key)
        safe_max = max(1, min(max_results, 100))
        payload = self._request("GET", f"/rest/api/3/issue/{issue_key}/comment", params={"maxResults": safe_max})
        comments = payload.get("comments", [])
        out: list[dict[str, Any]] = []
        for item in comments:
            author = item.get("author") or {}
            out.append(
                {
                    "id": item.get("id"),
                    "author": author.get("displayName"),
                    "created": item.get("created"),
                    "updated": item.get("updated"),
                    "body": item.get("body"),
                }
            )
        return {
            "issueKey": issue_key,
            "total": payload.get("total", len(out)),
            "maxResults": payload.get("maxResults", safe_max),
            "comments": out,
        }
