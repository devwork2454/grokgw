from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from grokgw.config import Settings
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
    data = resp.json()
    assert "error" in data
    assert data["error"]["type"] == "invalid_request_error"
    assert "gpt-4" in data["error"]["message"]


async def test_invalid_request_body(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
    })
    assert resp.status_code == 422
    data = resp.json()
    assert "error" in data
    assert data["error"]["type"] == "invalid_request_error"
    assert "messages" in data["error"]["message"]


async def test_content_parts_not_422(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [{"role": "user", "content": [{"type": "text", "text": "ping"}]}],
    })
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == "PONG"


async def test_tool_role_history_not_422(client):
    resp = await client.post("/v1/chat/completions", json={
        "model": "grok-4.5",
        "messages": [
            {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "bash", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "done"},
            {"role": "user", "content": [{"type": "text", "text": "next"}]},
        ],
        "tools": [{"type": "function", "function": {"name": "bash", "parameters": {}}}],
        "stream": False,
    })
    assert resp.status_code == 200


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


async def test_stream_holds_semaphore_until_done():
    """Streaming must keep the concurrency slot until the body finishes."""
    import asyncio

    active = 0
    max_active = 0
    release_gate = asyncio.Event()

    class SlowStreamRunner:
        async def complete(self, req):
            return {
                "id": "x",
                "object": "chat.completion",
                "created": 1,
                "model": req.model,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant", "content": "ok"},
                    "finish_reason": "stop",
                }],
            }

        async def stream(self, req):
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                yield 'data: {"choices":[{"delta":{"content":"a"}}]}\n\n'
                await release_gate.wait()
                yield 'data: {"choices":[{"delta":{}}],"finish_reason":"stop"}\n\n'
                yield "data: [DONE]\n\n"
            finally:
                active -= 1

    app = create_app(runner=SlowStreamRunner(), api_key=None, max_concurrent=1)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        async def stream_one():
            async with c.stream(
                "POST",
                "/v1/chat/completions",
                json={
                    "model": "grok-4.5",
                    "messages": [{"role": "user", "content": "x"}],
                    "stream": True,
                },
            ) as resp:
                assert resp.status_code == 200
                # read first chunk so stream() is running and holding the slot
                async for _ in resp.aiter_text():
                    break
                return

        t1 = asyncio.create_task(stream_one())
        # let first stream acquire the semaphore
        for _ in range(50):
            if active >= 1:
                break
            await asyncio.sleep(0.01)
        assert active == 1

        second_started = asyncio.Event()
        second_done = asyncio.Event()

        async def non_stream_second():
            second_started.set()
            resp = await c.post(
                "/v1/chat/completions",
                json={
                    "model": "grok-4.5",
                    "messages": [{"role": "user", "content": "y"}],
                    "stream": False,
                },
            )
            assert resp.status_code == 200
            second_done.set()

        t2 = asyncio.create_task(non_stream_second())
        await second_started.wait()
        # second request must block while stream holds the only slot
        await asyncio.sleep(0.05)
        assert not second_done.is_set()
        assert max_active == 1

        release_gate.set()
        await t1
        await t2
        assert second_done.is_set()
        assert max_active == 1


def _app_with_sessions(tmp_path: Path, api_key: str | None = None):
    sid = "019f69f6-cf7f-7711-b38e-45b3cecc1762"
    img = tmp_path / "%2Ftmp" / sid / "images" / "1.jpg"
    img.parent.mkdir(parents=True)
    img.write_bytes(b"\xff\xd8\xffJPEGTEST")
    settings = Settings(
        media_enabled=True,
        sessions_root=str(tmp_path),
        public_base="http://test",
        api_key=api_key,
    )
    return create_app(
        runner=FakeRunner(),
        api_key=api_key,
        max_concurrent=3,
        settings=settings,
    ), sid


async def test_media_image_ok(tmp_path: Path):
    app, sid = _app_with_sessions(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get(f"/v1/media/sessions/{sid}/images/1.jpg")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/jpeg")
    assert resp.content.startswith(b"\xff\xd8")


async def test_media_image_missing_404(tmp_path: Path):
    app, sid = _app_with_sessions(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get(f"/v1/media/sessions/{sid}/images/99.jpg")
    assert resp.status_code == 404


async def test_media_path_traversal_rejected(tmp_path: Path):
    app, sid = _app_with_sessions(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/v1/media/sessions/../etc/images/1.jpg")
    assert resp.status_code in (400, 404, 422)


async def test_media_requires_api_key_when_set(tmp_path: Path):
    app, sid = _app_with_sessions(tmp_path, api_key="secret-key")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get(f"/v1/media/sessions/{sid}/images/1.jpg")
        assert resp.status_code == 401
        resp2 = await c.get(
            f"/v1/media/sessions/{sid}/images/1.jpg",
            headers={"Authorization": "Bearer secret-key"},
        )
        assert resp2.status_code == 200


async def test_healthz_includes_media_flag(tmp_path: Path):
    app, _ = _app_with_sessions(tmp_path)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json().get("media_enabled") is True


async def test_healthz_deep_cli_checks_binary(tmp_path: Path):
    settings = Settings(backend="cli", media_enabled=False, grok_bin="true")
    app = create_app(runner=FakeRunner(), api_key=None, max_concurrent=1, settings=settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.get("/healthz", params={"deep": "true"})
    assert resp.status_code == 200
    data = resp.json()
    assert "checks" in data
    assert data["checks"]["grok_binary"]["ok"] is True
    assert data["status"] in ("ok", "degraded")


async def test_cli_ignored_sampling_header(tmp_path: Path):
    settings = Settings(backend="cli", media_enabled=False)
    app = create_app(runner=FakeRunner(), api_key=None, max_concurrent=1, settings=settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/v1/chat/completions",
            json={
                "model": "grok-4.5",
                "messages": [{"role": "user", "content": "x"}],
                "temperature": 0.1,
                "max_tokens": 10,
            },
        )
    assert resp.status_code == 200
    ignored = resp.headers.get("x-grokgw-ignored-params", "")
    assert "temperature" in ignored
    assert "max_tokens" in ignored


async def test_too_many_messages_rejected(client):
    settings = Settings(max_messages=2, media_enabled=False)
    app = create_app(runner=FakeRunner(), api_key=None, max_concurrent=1, settings=settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/v1/chat/completions",
            json={
                "model": "grok-4.5",
                "messages": [
                    {"role": "user", "content": "a"},
                    {"role": "assistant", "content": "b"},
                    {"role": "user", "content": "c"},
                ],
            },
        )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "context_length_exceeded"


async def test_messages_too_large_rejected(client):
    settings = Settings(max_message_chars=10, media_enabled=False)
    app = create_app(runner=FakeRunner(), api_key=None, max_concurrent=1, settings=settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/v1/chat/completions",
            json={
                "model": "grok-4.5",
                "messages": [{"role": "user", "content": "x" * 50}],
            },
        )
    assert resp.status_code == 400
    assert "too large" in resp.json()["error"]["message"]


async def test_body_too_large_rejected_by_content_length(client):
    settings = Settings(max_body_bytes=100, media_enabled=False)
    app = create_app(runner=FakeRunner(), api_key=None, max_concurrent=1, settings=settings)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        resp = await c.post(
            "/v1/chat/completions",
            content=b"x" * 200,
            headers={"Content-Type": "application/json", "Content-Length": "200"},
        )
    assert resp.status_code == 413
    assert resp.json()["error"]["code"] == "request_too_large"
