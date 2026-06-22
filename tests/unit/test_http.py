"""Unit tests for tools/_http.py retry/backoff behavior."""
import httpx
import pytest

from rs_mcp_server.tools import _http


async def _instant_sleep(*_args, **_kwargs):
    pass


def _inject(monkeypatch, handler):
    monkeypatch.setattr(_http._CLIENT, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(_http.asyncio, "sleep", _instant_sleep)  # skip real backoff


class TestRetry:
    @pytest.mark.anyio
    async def test_retries_transient_status_then_succeeds(self, monkeypatch):
        calls = []

        def handler(request):
            calls.append(request.url)
            if len(calls) < 2:
                return httpx.Response(503)
            return httpx.Response(200, json={"ok": True})

        _inject(monkeypatch, handler)
        result = await _http.http_get("https://wiki/api")
        assert result == {"ok": True}
        assert len(calls) == 2  # one retry

    @pytest.mark.anyio
    async def test_exhausts_retries_then_raises(self, monkeypatch):
        calls = []

        def handler(request):
            calls.append(request.url)
            return httpx.Response(503)

        _inject(monkeypatch, handler)
        with pytest.raises(httpx.HTTPStatusError):
            await _http.http_get("https://wiki/api")
        assert len(calls) == _http._CLIENT._max_retries + 1  # initial + retries

    @pytest.mark.anyio
    async def test_success_does_not_retry(self, monkeypatch):
        calls = []

        def handler(request):
            calls.append(request.url)
            return httpx.Response(200, json={"data": 1})

        _inject(monkeypatch, handler)
        assert await _http.http_get("https://wiki/api") == {"data": 1}
        assert len(calls) == 1
