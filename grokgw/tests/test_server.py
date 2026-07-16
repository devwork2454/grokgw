import pytest
from httpx import AsyncClient, ASGITransport
from grokgw.server import create_app


class FakeRunner:
    async def run(self, args):
        return {"text": "PONG", "stopReason": "EndTurn", "sessionId": "s1", "requestId": "q1"}

    async def run_stream(self, args):
        for ev in [
            {"type": "text", "data": "Hello"},
            {"type": "text", "data": " world"},
            {"type": "end", "stopReason": "EndTurn"},
        ]:
            yield ev


@pytest.fixture
def app():
    return create_app(runner=FakeRunner(), api_key=None, max_concurrent=3)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_chat_non_stream(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "ping"}],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["content"] == "PONG"
    assert data["choices"][0]["finish_reason"] == "stop"


async def test_models_list(client):
    resp = await client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    ids = [m["id"] for m in data["data"]]
    assert "grok-4.5" in ids
    assert "grok-build" in ids


async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


async def test_invalid_model(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "gpt-4",
        "messages": [{"role": "user", "content": "x"}],
    })
    assert resp.status_code == 400


async def test_invalid_request_body(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        # missing messages
    })
    assert resp.status_code == 422


async def test_chat_stream(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "hi"}],
        "stream": True,
    })
    assert resp.status_code == 200
    body = resp.text
    assert "data: " in body
    assert "Hello" in body
    assert "data: [DONE]" in body


@pytest.fixture
def authed_app():
    return create_app(runner=FakeRunner(), api_key="secret-key", max_concurrent=3)


@pytest.fixture
async def authed_client(authed_app):
    transport = ASGITransport(app=authed_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_auth_missing_key(authed_client):
    resp = await authed_client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "x"}],
    })
    assert resp.status_code == 401


async def test_auth_wrong_key(authed_client):
    resp = await authed_client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "x"}],
    }, headers={"Authorization": "Bearer wrong"})
    assert resp.status_code == 401


async def test_auth_correct_key(authed_client):
    resp = await authed_client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "x"}],
    }, headers={"Authorization": "Bearer secret-key"})
    assert resp.status_code == 200


async def test_healthz_no_auth_required(authed_client):
    """healthz should work even when API key is set (liveness probe)."""
    resp = await authed_client.get("/healthz")
    assert resp.status_code == 200
