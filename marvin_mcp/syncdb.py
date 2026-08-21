"""Read-only access to an Amazing Marvin CouchDB sync snapshot."""

from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

import httpx

from .config import Settings


class SyncDatabaseError(Exception):
    """A safe, credential-free error from sync database access."""


class SyncDatabaseClient:
    """Downloads and briefly caches task documents from CouchDB.

    Deliberately exposes no generic request or mutation method: this connector's
    sync database access is read-only.
    """

    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        cache_ttl: float = 45.0,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._cache_ttl = cache_ttl
        self._cached_at = 0.0
        self._cached_tasks: list[dict[str, Any]] | None = None
        self._lock = asyncio.Lock()

    def _missing_settings(self) -> list[str]:
        values = {
            "MARVIN_SYNC_SERVER": self._settings.sync_server,
            "MARVIN_SYNC_DATABASE": self._settings.sync_database,
            "MARVIN_SYNC_USER": self._settings.sync_user,
            "MARVIN_SYNC_PASSWORD": self._settings.sync_password,
        }
        return [name for name, value in values.items() if not value]

    async def tasks(self) -> list[dict[str, Any]]:
        missing = self._missing_settings()
        if missing:
            raise SyncDatabaseError(
                "Global task search requires Marvin sync database configuration; "
                f"missing: {', '.join(missing)}."
            )
        now = time.monotonic()
        if self._cached_tasks is not None and now - self._cached_at < self._cache_ttl:
            return self._cached_tasks
        async with self._lock:
            now = time.monotonic()
            if self._cached_tasks is not None and now - self._cached_at < self._cache_ttl:
                return self._cached_tasks
            tasks = await self._download_tasks()
            self._cached_tasks = tasks
            self._cached_at = time.monotonic()
            return tasks

    async def _download_tasks(self) -> list[dict[str, Any]]:
        server = self._settings.sync_server.rstrip("/")
        database = quote(self._settings.sync_database, safe="")
        url = f"{server}/{database}/_all_docs"
        try:
            async with httpx.AsyncClient(
                timeout=30.0, transport=self._transport
            ) as client:
                response = await client.get(
                    url,
                    params={"include_docs": "true"},
                    auth=(self._settings.sync_user, self._settings.sync_password),
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            raise SyncDatabaseError(
                f"Unable to read Marvin sync database: {type(exc).__name__}."
            ) from None
        rows = payload.get("rows", []) if isinstance(payload, dict) else []
        return [
            doc
            for row in rows
            if isinstance(row, dict)
            and not (row.get("value") or {}).get("deleted", False)
            and isinstance((doc := row.get("doc")), dict)
            and doc.get("db") == "Tasks"
            and not doc.get("_deleted", False)
        ]


def filter_tasks(
    tasks: list[dict[str, Any]],
    *,
    done: bool | None = None,
    query: str | None = None,
    parent_id: str | None = None,
    backburner: bool | None = None,
    scheduled: bool | None = None,
    scheduled_from: str | None = None,
    scheduled_to: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    label_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Apply the shared search/count predicates to task documents."""
    needle = query.casefold().strip() if query else None

    def matches(task: dict[str, Any]) -> bool:
        day = task.get("day")
        due = task.get("dueDate")
        labels = task.get("labelIds") or []
        if done is not None and bool(task.get("done", False)) is not done:
            return False
        if needle and needle not in f"{task.get('title', '')}\n{task.get('note', '')}".casefold():
            return False
        if parent_id is not None and task.get("parentId") != parent_id:
            return False
        if backburner is not None and bool(task.get("backburner", False)) is not backburner:
            return False
        if scheduled is not None and bool(day and day != "unassigned") is not scheduled:
            return False
        if scheduled_from is not None and (not day or day == "unassigned" or day < scheduled_from):
            return False
        if scheduled_to is not None and (not day or day == "unassigned" or day > scheduled_to):
            return False
        if due_from is not None and (not due or due < due_from):
            return False
        if due_to is not None and (not due or due > due_to):
            return False
        if label_ids and not set(label_ids).issubset(labels):
            return False
        return True

    return [task for task in tasks if matches(task)]


def task_result(task: dict[str, Any]) -> dict[str, Any]:
    """Return stable, useful metadata without leaking unrelated sync fields."""
    return {
        "id": task.get("_id"),
        "title": task.get("title"),
        "done": bool(task.get("done", False)),
        "parent_id": task.get("parentId"),
        "scheduled_date": task.get("day"),
        "due_date": task.get("dueDate"),
        "backburner": bool(task.get("backburner", False)),
        "label_ids": task.get("labelIds") or [],
        "note": task.get("note"),
    }
