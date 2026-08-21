"""Global task search and read-only CouchDB snapshot tests."""

import asyncio
from dataclasses import replace

import httpx

from marvin_mcp import server
from marvin_mcp.syncdb import SyncDatabaseClient, filter_tasks, task_result


TASKS = [
    {"_id": "t1", "db": "Tasks", "title": "Write ICAPS report", "note": "First draft", "done": False, "parentId": "p1", "day": "2026-08-21", "dueDate": "2026-08-25", "labelIds": ["work"]},
    {"_id": "t2", "db": "Tasks", "title": "Archived work", "note": "mentions icaps", "done": True, "parentId": "p1", "backburner": True, "labelIds": ["work", "later"]},
    {"_id": "t3", "db": "Tasks", "title": "Buy milk", "done": False, "parentId": "p2", "day": "2026-09-01"},
]

PLANNED_TASKS = [
    {"_id": "week", "db": "Tasks", "title": "Week", "plannedWeek": "2026-08-17"},
    {"_id": "month", "db": "Tasks", "title": "Month", "plannedMonth": "2026-08"},
    {"_id": "both", "db": "Tasks", "title": "Both", "plannedWeek": "2026-08-24", "plannedMonth": "2026-09"},
    {"_id": "neither", "db": "Tasks", "title": "Neither"},
    {"_id": "empty", "db": "Tasks", "title": "Empty", "plannedWeek": "", "plannedMonth": ""},
]


def test_shared_filters_cover_task_query_predicates():
    assert [t["_id"] for t in filter_tasks(TASKS, done=False)] == ["t1", "t3"]
    assert len(filter_tasks(TASKS, done=None)) == 3
    assert [t["_id"] for t in filter_tasks(TASKS, query="ICAPS")] == ["t1", "t2"]
    assert len(filter_tasks(TASKS, parent_id="p1")) == 2
    assert [t["_id"] for t in filter_tasks(TASKS, backburner=True)] == ["t2"]
    assert [t["_id"] for t in filter_tasks(TASKS, scheduled=False)] == ["t2"]
    assert [t["_id"] for t in filter_tasks(TASKS, scheduled=True)] == ["t1", "t3"]
    assert [t["_id"] for t in filter_tasks(TASKS, scheduled_to="2026-08-31")] == ["t1"]
    assert [t["_id"] for t in filter_tasks(TASKS, due_from="2026-08-24")] == ["t1"]
    assert len(filter_tasks(TASKS, label_ids=["work", "later"])) == 1


def test_text_search_treats_none_fields_as_empty_strings():
    task = {"_id": "nulls", "db": "Tasks", "title": None, "note": None}
    assert filter_tasks([task], query="None") == []


def test_notes_are_opt_in():
    assert "note" not in task_result(TASKS[0])
    assert task_result(TASKS[0], include_note=True)["note"] == "First draft"


def test_planning_filters_use_only_explicit_task_fields():
    ids = lambda **filters: [t["_id"] for t in filter_tasks(PLANNED_TASKS, **filters)]

    assert ids(planned_week="2026-08-17") == ["week"]
    assert ids(planned_month="2026-08") == ["month"]
    assert ids(planned_week="2026-08-24") == ["both"]
    assert ids(planned_month="2026-09") == ["both"]
    assert ids(week_planned=True) == ["week", "both"]
    assert ids(week_planned=False) == ["month", "neither", "empty"]
    assert ids(month_planned=True) == ["month", "both"]
    assert ids(month_planned=False) == ["week", "neither", "empty"]
    assert ids(planned=True) == ["week", "month", "both"]
    assert ids(planned=False) == ["neither", "empty"]


def test_task_results_include_nullable_planning_fields():
    assert task_result(PLANNED_TASKS[2])["planned_week"] == "2026-08-24"
    assert task_result(PLANNED_TASKS[2])["planned_month"] == "2026-09"
    assert task_result(PLANNED_TASKS[3])["planned_week"] is None
    assert task_result(PLANNED_TASKS[3])["planned_month"] is None
    assert task_result(PLANNED_TASKS[4])["planned_week"] is None
    assert task_result(PLANNED_TASKS[4])["planned_month"] is None


def sync_settings(settings):
    return replace(
        settings,
        sync_server="https://sync.example",
        sync_database="user-db",
        sync_user="sync-user",
        sync_password="sync-password",
    )


async def test_search_ignores_deleted_and_non_task_docs(settings):
    rows = [{"doc": task} for task in TASKS]
    rows += [
        {"doc": {"_id": "category", "db": "Categories"}},
        {"doc": {"_id": "gone", "db": "Tasks", "_deleted": True}},
        {"value": {"deleted": True}, "doc": {"_id": "gone2", "db": "Tasks"}},
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"rows": rows}))
    server.init(sync_settings(settings), transport=transport)
    result = await server.search_tasks.fn(done=None, query=None, parent_id=None,
        backburner=None, scheduled=None, scheduled_from=None, scheduled_to=None,
        due_from=None, due_to=None, label_ids=None, limit=100)
    assert result["total_matches"] == 3
    assert result["tasks"][0]["id"] == "t1"
    assert set(result["tasks"][0]) == {"id", "title", "done", "parent_id", "scheduled_date", "due_date", "planned_week", "planned_month", "backburner", "label_ids"}


async def test_count_uses_same_predicates_as_search(settings):
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"rows": [{"doc": t} for t in TASKS]}))
    server.init(sync_settings(settings), transport=transport)
    count = await server.count_tasks.fn(done=True, query="icaps", parent_id="p1",
        backburner=True, scheduled=None, scheduled_from=None, scheduled_to=None,
        due_from=None, due_to=None, label_ids=["work"])
    assert count == {"count": 1}


async def test_search_and_count_share_planning_filter_semantics(settings):
    transport = httpx.MockTransport(lambda request: httpx.Response(
        200, json={"rows": [{"doc": task} for task in PLANNED_TASKS]}
    ))
    server.init(sync_settings(settings), transport=transport)

    filters = {
        "planned_week": None,
        "planned_month": None,
        "week_planned": None,
        "month_planned": None,
        "planned": False,
    }
    search = await server.search_tasks.fn(**filters)
    count = await server.count_tasks.fn(**filters)

    assert [task["id"] for task in search["tasks"]] == ["neither", "empty"]
    assert search["total_matches"] == count["count"] == 2


async def test_missing_sync_configuration_only_affects_search(settings, transport):
    server.init(settings, transport=transport)
    result = await server.count_tasks.fn(done=False, query=None, parent_id=None,
        backburner=None, scheduled=None, scheduled_from=None, scheduled_to=None,
        due_from=None, due_to=None, label_ids=None)
    assert "MARVIN_SYNC_SERVER" in result["error"]
    assert "MARVIN_SYNC_PASSWORD" in result["error"]
    ordinary = await server.create_task.fn(title="Still works")
    assert "error" not in ordinary
    assert transport.requests[-1].url.path.endswith("/addTask")


async def test_snapshot_cache_reuse_and_expiry(settings):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"rows": [{"doc": TASKS[0]}]})
    client = SyncDatabaseClient(sync_settings(settings), httpx.MockTransport(handler), cache_ttl=0.01)
    await client.tasks()
    await client.tasks()
    assert calls == 1
    await asyncio.sleep(0.02)
    await client.tasks()
    assert calls == 2


async def test_sync_server_accepts_hostname_and_https_url(settings):
    requested_urls = []
    def handler(request):
        requested_urls.append(str(request.url.copy_with(query=None)))
        return httpx.Response(200, json={"rows": []})

    transport = httpx.MockTransport(handler)
    bare = replace(sync_settings(settings), sync_server="sync.example")
    qualified = replace(sync_settings(settings), sync_server="https://sync.example")
    await SyncDatabaseClient(bare, transport).tasks()
    await SyncDatabaseClient(qualified, transport).tasks()
    assert requested_urls == [
        "https://sync.example/user-db/_all_docs",
        "https://sync.example/user-db/_all_docs",
    ]


async def test_successful_task_mutation_invalidates_snapshot(settings):
    calls = 0
    def handler(request):
        nonlocal calls
        if request.url.path.endswith("/_all_docs"):
            calls += 1
            return httpx.Response(200, json={"rows": [{"doc": TASKS[0]}]})
        return httpx.Response(200, json={"ok": True})

    server.init(sync_settings(settings), transport=httpx.MockTransport(handler))
    await server._sync_client.tasks()
    await server._sync_client.tasks()
    assert calls == 1
    assert "error" not in await server.create_task.fn(title="new task")
    await server._sync_client.tasks()
    assert calls == 2
