import json

import httpx
import pytest

from grokgw.config import Settings
from grokgw.grok_runner import GrokRunError
from grokgw.models import ChatCompletionRequest, Message
from grokgw.proxy_runner import ProxyRunner


def _req(**kw) -> ChatCompletionRequest:
    base = dict(model="grok-4.5", messages=[Message(role="user", content="Hi")])
    base.update(kw)
    return ChatCompletionRequest(**base)


def _settings(tmp_path, **kw) -> Settings:
    auth = {
        "https://auth.x.ai::c": {
            "key": "tok",
            "refresh_token": "ref",
            "expires_at": "2099-01-01T00:00:00.000Z",
            "oidc_issuer": "https://auth.x.ai",
            "oidc_client_id": "c",
        }
    }
    p = tmp_path / "auth.json"
    p.write_text(json.dumps(auth))
    defaults = dict(
        backend="proxy",
        upstream_base="https://api.x.ai/v1",
        auth_path=str(p),
        proxy_url="socks5h://127.0.0.1:2080",
        proxy_mode="auto",
        timeout=30,
    )
    defaults.update(kw)
    return Settings(**defaults)


class _FakeResponse:
    def __init__(self, data: dict | str, status_code: int = 200):
        self.status_code = status_code
        self._data = data
        self.text = data if isinstance(data, str) else json.dumps(data)

    def json(self):
        if isinstance(self._data, str):
            return json.loads(self._data)
        return self._data


class _FakeStream:
    def __init__(self, lines: list[str], status_code: int = 200, error_body: str = ""):
        self.status_code = status_code
        self._lines = lines
        self._error_body = error_body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aread(self) -> bytes:
        return self._error_body.encode()

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeClient:
    def __init__(self, *, post_response: _FakeResponse | None = None, proxy: str | None = None):
        self.proxy = proxy
        self.post_calls: list[dict] = []
        self.get_calls: list[str] = []
        self._post_response = post_response or _FakeResponse(
            {"choices": [{"message": {"content": "PONG"}}]}
        )
        self._stream: _FakeStream | None = None

    async def post(self, url: str, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        return self._post_response

    async def get(self, url: str, **kwargs):
        self.get_calls.append(url)
        return _FakeResponse({}, status_code=200)

    def stream(self, method: str, url: str, **kwargs):
        self.post_calls.append({"url": url, "method": method, **kwargs})
        return self._stream or _FakeStream(
            ['data: {"choices":[{"delta":{"content":"hi"}}]}', "data: [DONE]"]
        )

    async def aclose(self):
        return None


async def test_complete_parses_response(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="always")
    client = _FakeClient()

    async def fake_get_client(self, proxy_url):
        client.proxy = proxy_url
        return client

    monkeypatch.setattr(ProxyRunner, "_get_client", fake_get_client)
    out = await ProxyRunner(s).complete(_req())
    assert out["choices"][0]["message"]["content"] == "PONG"
    assert client.proxy == s.proxy_url


async def test_upstream_payload_includes_sampling(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="always")
    client = _FakeClient()

    async def fake_get_client(self, proxy_url):
        return client

    monkeypatch.setattr(ProxyRunner, "_get_client", fake_get_client)
    await ProxyRunner(s).complete(
        _req(temperature=0.5, max_tokens=32, top_p=0.8, reasoning_effort="high")
    )
    payload = client.post_calls[0]["json"]
    assert payload["temperature"] == 0.5
    assert payload["max_tokens"] == 32
    assert payload["top_p"] == 0.8
    assert payload["reasoning_effort"] == "high"
    assert payload["stream"] is False


async def test_always_uses_proxy(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="always", proxy_url="socks5h://1.2.3.4:1080")
    client = _FakeClient(
        post_response=_FakeResponse({"error": {"message": "auth failed"}}, status_code=401)
    )

    async def fake_get_client(self, proxy_url):
        client.proxy = proxy_url
        return client

    monkeypatch.setattr(ProxyRunner, "_get_client", fake_get_client)
    with pytest.raises(GrokRunError, match="auth"):
        await ProxyRunner(s).complete(_req())
    assert client.proxy == "socks5h://1.2.3.4:1080"


async def test_never_uses_no_proxy(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="never")
    client = _FakeClient(post_response=_FakeResponse({"choices": [{"message": {"content": "x"}}]}))

    async def fake_get_client(self, proxy_url):
        client.proxy = proxy_url
        return client

    monkeypatch.setattr(ProxyRunner, "_get_client", fake_get_client)
    await ProxyRunner(s).complete(_req())
    assert client.proxy is None


async def test_auto_probes_direct_first(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="auto", proxy_url="socks5h://127.0.0.1:2080")
    client = _FakeClient()
    probes: list[str | None] = []

    async def fake_probe(self, url, proxy_url):
        probes.append(proxy_url)
        return proxy_url is None  # direct OK

    async def fake_get_client(self, proxy_url):
        client.proxy = proxy_url
        return client

    monkeypatch.setattr(ProxyRunner, "_probe", fake_probe)
    monkeypatch.setattr(ProxyRunner, "_get_client", fake_get_client)
    out = await ProxyRunner(s).complete(_req())
    assert out["choices"][0]["message"]["content"] == "PONG"
    assert probes == [None]
    assert client.proxy is None


async def test_timeout_raises(monkeypatch, tmp_path):
    s = _settings(tmp_path, proxy_mode="never")

    class TimeoutClient(_FakeClient):
        async def post(self, url: str, **kwargs):
            raise httpx.ReadTimeout("slow")

    client = TimeoutClient()

    async def fake_get_client(self, proxy_url):
        return client

    monkeypatch.setattr(ProxyRunner, "_get_client", fake_get_client)
    with pytest.raises(TimeoutError):
        await ProxyRunner(s).complete(_req())
