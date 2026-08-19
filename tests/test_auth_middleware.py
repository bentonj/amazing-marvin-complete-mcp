import httpx

from marvin_mcp.__main__ import BearerAuthMiddleware


async def dummy_app(scope, receive, send):
    await send(
        {"type": "http.response.start", "status": 200, "headers": []}
    )
    await send({"type": "http.response.body", "body": b"ok"})


async def test_rejects_without_token():
    app = BearerAuthMiddleware(dummy_app, "tst-tok-1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        assert (await c.get("/mcp")).status_code == 401
        assert (
            await c.get("/mcp", headers={"Authorization": "Bearer wrong"})
        ).status_code == 401


async def test_accepts_correct_token():
    app = BearerAuthMiddleware(dummy_app, "tst-tok-1")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        resp = await c.get("/mcp", headers={"Authorization": "Bearer tst-tok-1"})
        assert resp.status_code == 200
