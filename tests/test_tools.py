"""Tests of the MCP tools (via .fn - FastMCP's FunctionTool wrapper)."""

import httpx

from marvin_mcp import server


async def test_create_task_payload(init_server, transport):
    await server.create_task.fn(
        title="Test task",
        parent_id="cat1",
        day="today",
        priority=3,
        frog=2,
        note="a note",
    )
    body = transport.last_json()
    assert body["title"] == "Test task"
    assert body["parentId"] == "cat1"
    assert body["isStarred"] == 3
    assert body["isFrogged"] == 2
    assert body["day"]  # today's date, set
    assert body["done"] is False


async def test_set_priority_builds_fieldupdates_setters(init_server, transport):
    result = await server.set_priority.fn(item_id="t1", priority=2)
    assert "error" not in result
    body = transport.last_json()
    assert body["itemId"] == "t1"
    keys = [s["key"] for s in body["setters"]]
    assert "isStarred" in keys
    assert "fieldUpdates.isStarred" in keys
    assert "updatedAt" in keys


async def test_set_priority_zero_clears(init_server, transport):
    await server.set_priority.fn(item_id="t1", priority=0)
    setters = {s["key"]: s["val"] for s in transport.last_json()["setters"]}
    assert setters["isStarred"] is False


async def test_set_priority_requires_some_field(init_server, transport):
    result = await server.set_priority.fn(item_id="t1")
    assert "error" in result
    assert transport.requests == []


async def test_update_task_never_touches_done(init_server, transport):
    await server.update_task.fn(item_id="t1", title="New name", day="unassigned")
    keys = [s["key"] for s in transport.last_json()["setters"]]
    assert "done" not in keys
    assert "title" in keys and "day" in keys


async def test_unmark_done_sets_done_false(init_server, transport):
    await server.unmark_done.fn(item_id="t1")
    setters = {s["key"]: s["val"] for s in transport.last_json()["setters"]}
    assert setters["done"] is False


async def test_mark_done_uses_markdone_endpoint(init_server, transport):
    await server.mark_done.fn(item_id="t1")
    assert transport.requests[-1].url.path.endswith("/markDone")


async def test_create_category_uses_doc_create(init_server, transport):
    await server.create_category_or_project.fn(
        title="MCP-TEST", kind="category", parent_id="root"
    )
    req = transport.requests[-1]
    assert req.url.path.endswith("/doc/create")
    body = transport.last_json()
    assert body["db"] == "Categories"
    assert body["type"] == "category"
    assert req.headers.get("X-Full-Access-Token")


async def test_create_project_uses_addproject(init_server, transport):
    await server.create_category_or_project.fn(
        title="Test project", kind="project", parent_id="cat1"
    )
    req = transport.requests[-1]
    assert req.url.path.endswith("/addProject")
    assert req.headers.get("X-API-Token")


async def test_record_habit_and_undo(init_server, transport):
    await server.record_habit.fn(habit_id="h1", value=2)
    body = transport.last_json()
    assert body["habitId"] == "h1"
    assert body["value"] == 2
    assert body["updateDB"] is True
    assert "time" in body

    await server.record_habit.fn(habit_id="h1", undo=True)
    body = transport.last_json()
    assert body["undo"] is True
    assert "value" not in body


async def test_create_time_block_doc_shape(init_server, transport):
    await server.create_time_block.fn(
        title="Morning", date="2026-08-20", start_time="08:00", duration_minutes=180
    )
    body = transport.last_json()
    assert body["db"] == "PlannerItems"
    assert body["time"] == "08:00"
    assert body["duration"] == "180"


async def test_time_blocks_include_category_mapping(init_server, transport):
    transport.responses["/todayTimeBlocks"] = httpx.Response(
        200, json=[{"title": "Morning", "time": "08:00"}]
    )
    transport.responses["/doc"] = httpx.Response(
        200, json={"_id": "strategySettings.plannerSmartLists", "val": {"Morning": "cat1"}}
    )
    result = await server.get_today_time_blocks.fn()
    assert result["count"] == 1
    assert result["title_to_category_or_smartlist"] == {"Morning": "cat1"}


async def test_tool_errors_are_returned_not_raised(init_server, transport):
    transport.responses["/todayItems"] = httpx.Response(500, text="boom")
    result = await server.get_today_items.fn()
    assert "error" in result


async def test_get_time_tracks_caps_at_100(init_server, transport):
    result = await server.get_time_tracks.fn(task_ids=["x"] * 101)
    assert "error" in result
    assert transport.requests == []


async def test_get_kudos_uses_api_token(init_server, transport):
    transport.responses["/kudos"] = httpx.Response(
        200, json={"kudos": 0, "level": 1, "kudosRemaining": 350}
    )
    result = await server.get_kudos.fn()
    req = transport.requests[-1]
    assert req.method == "GET" and req.url.path.endswith("/kudos")
    assert req.headers.get("X-API-Token")
    assert not req.headers.get("X-Full-Access-Token")
    assert result["kudos"]["level"] == 1


async def test_claim_reward_points_payload_defaults_today(init_server, transport):
    await server.claim_reward_points.fn(points=1.5, item_id="t1")
    body = transport.last_json()
    assert body["op"] == "CLAIM"
    assert body["points"] == 1.5
    assert body["itemId"] == "t1"
    assert body["date"]  # today's date (server timezone), set
    assert transport.requests[-1].url.path.endswith("/claimRewardPoints")


async def test_unclaim_reward_points_payload(init_server, transport):
    await server.unclaim_reward_points.fn(item_id="t1", date="2026-08-19")
    body = transport.last_json()
    assert body == {"itemId": "t1", "date": "2026-08-19", "op": "UNCLAIM"}


async def test_spend_reward_points_payload(init_server, transport):
    await server.spend_reward_points.fn(points=2)
    body = transport.last_json()
    assert body["op"] == "SPEND"
    assert body["points"] == 2
    assert "itemId" not in body


async def test_reset_reward_points_requires_full_access(init_server, transport):
    await server.reset_reward_points.fn()
    req = transport.requests[-1]
    assert req.url.path.endswith("/resetRewardPoints")
    assert req.headers.get("X-Full-Access-Token")
    assert not req.headers.get("X-API-Token")


async def test_reward_summary_filters_profile(init_server, transport):
    transport.responses["/claimRewardPoints"] = httpx.Response(
        200,
        json={
            "email": "x@example.com",
            "rewardPointsEarned": 5,
            "rewardPointsSpent": 2,
            "rewardPointsEarnedToday": 1,
            "rewardPointsSpentToday": 0,
            "rewardPointsLastDate": "2026-08-19",
        },
    )
    result = await server.claim_reward_points.fn(points=1, item_id="MANUAL")
    summary = result["reward_points"]
    assert summary["balance"] == 3
    assert "email" not in summary


async def test_unclaim_manual_guarded_without_api_call(init_server, transport):
    """MANUAL awards cannot be undone (live test 2026-08-19: 404) -
    the tool must refuse locally without burning an API call."""
    result = await server.unclaim_reward_points.fn(item_id="MANUAL")
    assert "error" in result
    assert "spend_reward_points" in result["error"]
    assert transport.requests == []


async def test_unmark_done_clears_done_and_doneat(init_server, transport):
    await server.unmark_done.fn(item_id="t1")
    setters = {s["key"]: s["val"] for s in transport.last_json()["setters"]}
    assert setters["done"] is False
    assert setters["doneAt"] is None
    assert "fieldUpdates.doneAt" in setters


def test_tool_annotations():
    """The standard hints must be set: get_* read-only, deletes/reset
    destructive, all other writes explicitly non-destructive."""
    assert server.get_categories.annotations.readOnlyHint is True
    assert server.get_today_items.annotations.readOnlyHint is True
    assert server.delete_task.annotations.destructiveHint is True
    assert server.reset_reward_points.annotations.destructiveHint is True
    assert server.delete_reminder.annotations.destructiveHint is True
    assert server.create_task.annotations.destructiveHint is False
    assert server.create_task.annotations.idempotentHint is False
    assert server.mark_done.annotations.idempotentHint is True
    assert server.mark_done.annotations.destructiveHint is False
    # Every tool only talks to Marvin's API - no open world.
    assert server.create_task.annotations.openWorldHint is False


async def test_list_habits_uses_raw_with_full_access(init_server, transport):
    """Non-raw /habits misses never-recorded habits (lazy tracking registry,
    live test 2026-08-19) - the tool must request raw=1 with the Full Access Token."""
    transport.responses["/habits"] = httpx.Response(
        200, json=[{"_id": "h1", "title": "Test habit", "history": []}]
    )
    result = await server.list_habits.fn()
    req = transport.requests[-1]
    assert req.url.params.get("raw") == "1"
    assert req.headers.get("X-Full-Access-Token")
    assert not req.headers.get("X-API-Token")
    assert result["count"] == 1
    assert result["habits"][0]["title"] == "Test habit"


async def test_update_task_sets_label_ids(init_server, transport):
    await server.update_task.fn(item_id="t1", label_ids=["l1", "l2"])
    setters = {s["key"]: s["val"] for s in transport.last_json()["setters"]}
    assert setters["labelIds"] == ["l1", "l2"]
    assert "fieldUpdates.labelIds" in setters


async def test_update_task_empty_label_ids_clears(init_server, transport):
    await server.update_task.fn(item_id="t1", label_ids=[])
    setters = {s["key"]: s["val"] for s in transport.last_json()["setters"]}
    assert setters["labelIds"] == []


async def test_record_habit_integral_value_sent_as_int(init_server, transport):
    """/updateHabit responds 400 to 'value': 1.0 but 200 to 1 (live test
    2026-08-19) - integral values must be serialized as int."""
    await server.record_habit.fn(habit_id="h1", value=1.0)
    raw = transport.requests[-1].content.decode()
    assert '"value":1}' in raw.replace(" ", "")  # int, not 1.0

    await server.record_habit.fn(habit_id="h1", value=2.5)
    body = transport.last_json()
    assert body["value"] == 2.5
