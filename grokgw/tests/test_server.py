import pytest
from httpx import ASGITransport, AsyncClient

from grokgw.grok_runner import GrokRunError
from grokgw.server import create_app


class FakeRunner:
    async def complete(self, req):
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 1,
            "model": req.model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "PONG"},
                "finish_reason": "stop",
            }],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    async def stream(self, req):
        yield (
            'data: {"id":"c1","object":"chat.completion.chunk","created":1,'
            '"model":"grok-4.5","choices":[{"index":0,"delta":{"content":"Hello"},'
            '"finish_reason":null}]}\n\n'
        )
        yield (
            'data: {"id":"c1","object":"chat.completion.chunk","created":1,'
            '"model":"grok-4.5","choices":[{"index":0,"delta":{"content":" world"},'
            '"finish_reason":null}]}\n\n'
        )
        yield (
            'data: {"id":"c1","object":"chat.completion.chunk","created":1,'
            '"model":"grok-4.5","choices":[{"index":0,"delta":{},'
            '"finish_reason":"stop"}]}\n\n'
        )
        yield "data: [DONE]\n\n"


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
    resp = await authed_client.get("/healthz")
    assert resp.status_code == 200


class AuthFailRunner:
    async def complete(self, req):
        raise GrokRunError("auth error: please run grok login", 1, "auth error")

    async def stream(self, req):
        raise GrokRunError("auth error", 1, "auth error")
        yield


@pytest.fixture
def authfail_app():
    return create_app(runner=AuthFailRunner(), api_key=None, max_concurrent=3)


@pytest.fixture
async def authfail_client(authfail_app):
    transport = ASGITransport(app=authfail_app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_auth_expired_returns_401(authfail_client):
    resp = await authfail_client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": "x"}],
    })
    assert resp.status_code == 401
    data = resp.json()
    assert "grok login" in data["error"]["message"].lower()


async def test_generic_runner_error_returns_502():
    class FailRunner:
        async def complete(self, req):
            raise GrokRunError("some other error", 1, "error")

        async def stream(self, req):
            raise GrokRunError("error", 1, "error")
            yield

    app = create_app(runner=FailRunner(), api_key=None, max_concurrent=3)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/v1/chat/completions", json={
            "model": "grok-4.5",
            "messages": [{"role": "user", "content": "x"}],
        })
        assert resp.status_code == 502


async def test_timeout_returns_504():
    class TimeoutRunner:
        async def complete(self, req):
            raise TimeoutError("grok timed out after 120s")

        async def stream(self, req):
            raise TimeoutError("timed out")
            yield

    app = create_app(runner=TimeoutRunner(), api_key=None, max_concurrent=3)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/v1/chat/completions", json={
            "model": "grok-4.5",
            "messages": [{"role": "user", "content": "x"}],
        })
        assert resp.status_code == 504


async def test_stream_runner_error_emits_sse_error_frame():
    class StreamFailRunner:
        async def complete(self, req):
            return {"choices": [{"message": {"content": "unused"}}]}

        async def stream(self, req):
            yield 'data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            raise GrokRunError("upstream boom", 1, "upstream boom")
            yield

    app = create_app(runner=StreamFailRunner(), api_key=None, max_concurrent=3)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post("/v1/chat/completions", json={
            "model": "grok-4.5",
            "messages": [{"role": "user", "content": "x"}],
            "stream": True,
        })
        assert resp.status_code == 200
        body = resp.text
        assert "partial" in body
        assert "upstream boom" in body or "error" in body
        assert "data: [DONE]" in body
