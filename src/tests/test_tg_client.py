"""
test_tg_client.py — Telegram ChatOps bot: async DCN API client.

The client is the only component that touches the network. Tests use httpx's
built-in MockTransport (no extra dependency, no live server) to assert:
  - correct HTTP method, path, query params and JSON body per endpoint,
  - parsed JSON is returned,
  - HTTP errors and transport errors are normalised to DCNError.

Async coroutines are driven with asyncio.run() so we don't depend on
pytest-asyncio being installed in the runtime venv.
"""

import asyncio
import json

import httpx
import pytest

from telegram_bot.dcn_client import DCNClient, DCNError


def run(coro):
    return asyncio.run(coro)


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestHealth:
    def test_health_ok(self):
        def handler(req):
            assert req.method == "GET"
            assert req.url.path == "/api/health"
            return httpx.Response(200, json={"status": "ok", "devices_loaded": 10})

        async def go():
            async with make_client(handler) as c:
                return await DCNClient(base_url="http://dcn", client=c).health()

        assert run(go())["status"] == "ok"


class TestListDevices:
    def test_passes_filters_as_query_params(self):
        seen = {}

        def handler(req):
            seen["path"] = req.url.path
            seen["q"] = dict(req.url.params)
            return httpx.Response(200, json=[{"hostname": "h1"}])

        async def go():
            async with make_client(handler) as c:
                client = DCNClient(base_url="http://dcn", client=c)
                return await client.list_devices(site="DE-FRA", search="core")

        data = run(go())
        assert data == [{"hostname": "h1"}]
        assert seen["path"] == "/api/devices"
        assert seen["q"].get("site") == "DE-FRA"
        assert seen["q"].get("search") == "core"


class TestAsk:
    def test_posts_prompt_to_orchestrator(self):
        seen = {}

        def handler(req):
            seen["path"] = req.url.path
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={"rendered": "ok", "agent": "IncidentAgent"})

        async def go():
            async with make_client(handler) as c:
                client = DCNClient(base_url="http://dcn", client=c)
                return await client.ask("why is bgp down?")

        data = run(go())
        assert seen["path"] == "/api/mv/orchestrator"
        assert seen["body"]["prompt"] == "why is bgp down?"
        assert data["rendered"] == "ok"


class TestIncident:
    def test_posts_ip_and_default_dtype(self):
        seen = {}

        def handler(req):
            seen["path"] = req.url.path
            seen["body"] = json.loads(req.content)
            return httpx.Response(200, json={"ok": True})

        async def go():
            async with make_client(handler) as c:
                client = DCNClient(base_url="http://dcn", client=c)
                return await client.incident("10.0.0.1")

        run(go())
        assert seen["path"] == "/api/incident"
        assert seen["body"]["ip"] == "10.0.0.1"
        assert seen["body"]["dtype"] == "junos"


class TestGetEndpointPaths:
    def _path_for(self, method_name, *args):
        seen = {}

        def handler(req):
            seen["path"] = req.url.path
            return httpx.Response(200, json={})

        async def go():
            async with make_client(handler) as c:
                client = DCNClient(base_url="http://dcn", client=c)
                await getattr(client, method_name)(*args)

        run(go())
        return seen["path"]

    def test_topology_path(self):
        assert self._path_for("topology") == "/api/mv/topology"

    def test_report_bgp_path(self):
        assert self._path_for("report_bgp") == "/api/report/bgp"

    def test_sites_path(self):
        assert self._path_for("list_sites") == "/api/sites"


class TestErrorHandling:
    def test_http_500_raises_dcnerror(self):
        def handler(req):
            return httpx.Response(500, text="boom")

        async def go():
            async with make_client(handler) as c:
                await DCNClient(base_url="http://dcn", client=c).health()

        with pytest.raises(DCNError):
            run(go())

    def test_connect_error_raises_dcnerror(self):
        def handler(req):
            raise httpx.ConnectError("connection refused")

        async def go():
            async with make_client(handler) as c:
                await DCNClient(base_url="http://dcn", client=c).health()

        with pytest.raises(DCNError):
            run(go())

    def test_post_http_500_raises_dcnerror(self):
        def handler(req):
            return httpx.Response(500, text="boom")

        async def go():
            async with make_client(handler) as c:
                await DCNClient(base_url="http://dcn", client=c).ask("x")

        with pytest.raises(DCNError):
            run(go())
