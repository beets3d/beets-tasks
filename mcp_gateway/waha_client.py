from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from django.conf import settings
from psycopg import connect
from psycopg.rows import dict_row


class WahaClientError(Exception):
    pass


@dataclass
class WahaDbConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    sslmode: str


class WahaClient:
    def __init__(self) -> None:
        self.cfg = WahaDbConfig(
            host=settings.WAHA_DB_HOST,
            port=settings.WAHA_DB_PORT,
            database=settings.WAHA_DB_NAME,
            user=settings.WAHA_DB_USER,
            password=settings.WAHA_DB_PASSWORD,
            sslmode=settings.WAHA_DB_SSLMODE,
        )
        if not self.cfg.host or not self.cfg.database or not self.cfg.user:
            raise WahaClientError("WAHA DB config is incomplete")

    def _connect(self):
        return connect(
            host=self.cfg.host,
            port=self.cfg.port,
            dbname=self.cfg.database,
            user=self.cfg.user,
            password=self.cfg.password,
            sslmode=self.cfg.sslmode,
            connect_timeout=8,
        )

    @staticmethod
    def _fmt_dt(value: Any) -> str | None:
        if isinstance(value, datetime):
            return value.isoformat()
        return None if value is None else str(value)

    @staticmethod
    def _parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        raw = value.strip()
        if not raw:
            return None
        # Accept both "...Z" and explicit offset formats.
        normalized = raw.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError as exc:
            raise WahaClientError(f"Invalid ISO datetime: {value}") from exc

    def list_recent_chats(self, limit: int = 20) -> list[dict[str, Any]]:
        safe_limit = max(1, min(limit, 100))
        sql = """
            SELECT
                chat_id,
                MAX(timestamp) AS last_message_at,
                COUNT(*)::int AS message_count,
                MAX(COALESCE(NULLIF(TRIM(push_name), ''), 'Unknown')) AS push_name
            FROM waha_messages
            GROUP BY chat_id
            ORDER BY MAX(timestamp) DESC
            LIMIT %s
        """
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (safe_limit,))
                rows = cur.fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "chatId": row["chat_id"],
                    "lastMessageAt": self._fmt_dt(row["last_message_at"]),
                    "messageCount": row["message_count"],
                    "pushName": row["push_name"],
                }
            )
        return out

    def get_chat_messages(self, chat_id: str, limit: int = 50, before: str | None = None) -> dict[str, Any]:
        if not chat_id or not chat_id.strip():
            raise WahaClientError("chatId is required")
        safe_limit = max(1, min(limit, 500))

        params: list[Any] = [chat_id]
        before_clause = ""
        if before:
            before_clause = " AND timestamp < %s"
            params.append(before)
        params.append(safe_limit)

        sql = f"""
            SELECT
                message_id,
                chat_id,
                sender,
                recipient,
                role,
                message_type,
                content,
                caption,
                media_url,
                push_name,
                timestamp
            FROM waha_messages
            WHERE chat_id = %s
            {before_clause}
            ORDER BY timestamp DESC
            LIMIT %s
        """
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

        messages: list[dict[str, Any]] = []
        for row in rows:
            messages.append(
                {
                    "messageId": row.get("message_id"),
                    "chatId": row.get("chat_id"),
                    "sender": row.get("sender"),
                    "recipient": row.get("recipient"),
                    "role": row.get("role"),
                    "messageType": row.get("message_type"),
                    "content": row.get("content"),
                    "caption": row.get("caption"),
                    "mediaUrl": row.get("media_url"),
                    "pushName": row.get("push_name"),
                    "timestamp": self._fmt_dt(row.get("timestamp")),
                }
            )

        return {
            "chatId": chat_id,
            "count": len(messages),
            "messages": messages,
        }

    def search_messages(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        if not query or not query.strip():
            raise WahaClientError("query is required")
        safe_limit = max(1, min(limit, 200))
        sql = """
            SELECT
                message_id,
                chat_id,
                role,
                content,
                sender,
                recipient,
                timestamp
            FROM waha_messages
            WHERE content ILIKE %s
            ORDER BY timestamp DESC
            LIMIT %s
        """
        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, (f"%{query}%", safe_limit))
                rows = cur.fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "messageId": row.get("message_id"),
                    "chatId": row.get("chat_id"),
                    "role": row.get("role"),
                    "content": row.get("content"),
                    "sender": row.get("sender"),
                    "recipient": row.get("recipient"),
                    "timestamp": self._fmt_dt(row.get("timestamp")),
                }
            )
        return out

    def get_messages_in_window(
        self,
        *,
        start_time: str | None = None,
        end_time: str | None = None,
        hours: int | None = None,
        chat_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        safe_limit = max(1, min(limit, 500))
        parsed_start = self._parse_iso(start_time)
        parsed_end = self._parse_iso(end_time)

        if hours is not None:
            if not isinstance(hours, int) or hours < 1 or hours > 720:
                raise WahaClientError("hours must be an integer between 1 and 720")
            parsed_start = datetime.now(timezone.utc) - timedelta(hours=hours)

        if parsed_start is None and parsed_end is None:
            raise WahaClientError("Provide hours or startTime/endTime")

        where_parts = ["1=1"]
        params: list[Any] = []

        if chat_id:
            where_parts.append("chat_id = %s")
            params.append(chat_id)
        if parsed_start is not None:
            where_parts.append("timestamp >= %s")
            params.append(parsed_start)
        if parsed_end is not None:
            where_parts.append("timestamp <= %s")
            params.append(parsed_end)

        params.append(safe_limit)
        sql = f"""
            SELECT
                message_id,
                chat_id,
                role,
                content,
                sender,
                recipient,
                message_type,
                timestamp
            FROM waha_messages
            WHERE {' AND '.join(where_parts)}
            ORDER BY timestamp DESC
            LIMIT %s
        """

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

        messages: list[dict[str, Any]] = []
        for row in rows:
            messages.append(
                {
                    "messageId": row.get("message_id"),
                    "chatId": row.get("chat_id"),
                    "role": row.get("role"),
                    "content": row.get("content"),
                    "sender": row.get("sender"),
                    "recipient": row.get("recipient"),
                    "messageType": row.get("message_type"),
                    "timestamp": self._fmt_dt(row.get("timestamp")),
                }
            )

        return {
            "window": {
                "startTime": self._fmt_dt(parsed_start),
                "endTime": self._fmt_dt(parsed_end),
                "hours": hours,
                "chatId": chat_id,
                "limit": safe_limit,
            },
            "count": len(messages),
            "messages": messages,
        }

    def get_user_messages_recent_days(
        self,
        *,
        days: int,
        keyword: str | None = None,
        chat_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        if not isinstance(days, int) or days < 1 or days > 90:
            raise WahaClientError("days must be an integer between 1 and 90")
        safe_limit = max(1, min(limit, 500))
        start_dt = datetime.now(timezone.utc) - timedelta(days=days)

        where_parts = ["role = %s", "timestamp >= %s"]
        params: list[Any] = ["User", start_dt]

        if chat_id and chat_id.strip():
            where_parts.append("chat_id = %s")
            params.append(chat_id.strip())

        if keyword and keyword.strip():
            where_parts.append("content ILIKE %s")
            params.append(f"%{keyword.strip()}%")

        params.append(safe_limit)
        sql = f"""
            SELECT
                message_id,
                chat_id,
                role,
                content,
                sender,
                recipient,
                message_type,
                timestamp
            FROM waha_messages
            WHERE {' AND '.join(where_parts)}
            ORDER BY timestamp DESC
            LIMIT %s
        """

        with self._connect() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(sql, tuple(params))
                rows = cur.fetchall()

        messages: list[dict[str, Any]] = []
        for row in rows:
            messages.append(
                {
                    "messageId": row.get("message_id"),
                    "chatId": row.get("chat_id"),
                    "role": row.get("role"),
                    "content": row.get("content"),
                    "sender": row.get("sender"),
                    "recipient": row.get("recipient"),
                    "messageType": row.get("message_type"),
                    "timestamp": self._fmt_dt(row.get("timestamp")),
                }
            )

        return {
            "filter": {
                "days": days,
                "role": "User",
                "keyword": keyword,
                "chatId": chat_id,
                "startTime": self._fmt_dt(start_dt),
                "limit": safe_limit,
            },
            "count": len(messages),
            "messages": messages,
        }
