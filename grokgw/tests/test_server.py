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
