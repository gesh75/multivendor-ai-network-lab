"""
Tests for the MCP server (Day-9).

Run:
    cd 04_Scripts_Tools/DCN_Network_Tool && pytest test_mcp_server.py -v

The tools layer is HTTP — we mock `requests` to avoid needing a live Flask.
The server layer is tested by listing the FastMCP registries to confirm the
decorators registered the right surface.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "src"))

# Make sure tools default to localhost — won't matter because we mock requests.
os.environ.setdefault("DCN_API_URL", "http://localhost:5757")

pytest.importorskip("mcp.server.fastmcp")

from mcp_server import tools  # noqa: E402
from mcp_server.server import mcp  # noqa: E402


# ─── Helpers ────────────────────────────────────────────────────────────────


def _mock_response(payload, status=200):
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = payload
    resp.raise_for_status = MagicMock()
    return resp


# ─── Tools — read tier ──────────────────────────────────────────────────────


class TestListDevices:
    def test_returns_all_when_no_filter(self):
        sample = {"devices": [
            {"hostname": "de-fra-core-01", "site": "DE-FRA", "vendor": "frr",  "role": "core"},
            {"hostname": "uk-lon-fw-01",   "site": "UK-LON", "vendor": "juniper", "role": "firewall"},
        ]}
        with patch("mcp_server.tools.requests.get", return_value=_mock_response(sample)):
            out = tools.list_devices()
        assert out["count"] == 2

    def test_filters_by_site(self):
        sample = {"devices": [
            {"hostname": "de-fra-core-01", "site": "DE-FRA", "vendor": "frr",     "role": "core"},
            {"hostname": "uk-lon-fw-01",   "site": "UK-LON", "vendor": "juniper", "role": "firewall"},
        ]}
        with patch("mcp_server.tools.requests.get", return_value=_mock_response(sample)):
            out = tools.list_devices(site="de-fra")
        assert out["count"] == 1
        assert out["devices"][0]["hostname"] == "de-fra-core-01"

    def test_filters_by_vendor_matches_os(self):
        sample = {"devices": [
            {"hostname": "a", "vendor": "frr"},
            {"hostname": "b", "vendor": "juniper", "os": "junos"},
        ]}
        with patch("mcp_server.tools.requests.get", return_value=_mock_response(sample)):
            out = tools.list_devices(vendor="junos")
        assert out["count"] == 1
        assert out["devices"][0]["hostname"] == "b"

    def test_filters_by_role(self):
        sample = {"devices": [
            {"hostname": "a", "role": "core"},
            {"hostname": "b", "role": "edge"},
        ]}
        with patch("mcp_server.tools.requests.get", return_value=_mock_response(sample)):
            out = tools.list_devices(role="edge")
        assert out["count"] == 1


class TestBgpStatus:
    def test_calls_run_endpoint(self):
        sample = {"hostname": "de-fra-core-01", "output": "Established"}
        with patch("mcp_server.tools.requests.post", return_value=_mock_response(sample)) as p:
            out = tools.bgp_status("de-fra-core-01")
        # Verify the request was correct
        args, kwargs = p.call_args
        assert args[0].endswith("/api/run")
        assert kwargs["json"]["hostname"] == "de-fra-core-01"
        assert "bgp summary" in kwargs["json"]["raw"].lower()
        assert out["output"] == "Established"


class TestRunCommand:
    def test_posts_to_run_endpoint(self):
        sample = {"hostname": "leaf2", "output": "...", "rc": 0}
        with patch("mcp_server.tools.requests.post",
                   return_value=_mock_response(sample)) as p:
            out = tools.run_command("leaf2", "show version")
        args, kwargs = p.call_args
        assert args[0].endswith("/api/run")
        assert kwargs["json"] == {"hostname": "leaf2", "raw": "show version"}
        assert out["rc"] == 0

    def test_passes_command_verbatim(self):
        with patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({})) as p:
            tools.run_command("de-fra-core-01", "show ip ospf neighbor | json")
        assert p.call_args.kwargs["json"]["raw"] == "show ip ospf neighbor | json"


class TestGetConfig:
    _devices = {"devices": [
        {"hostname": "de-fra-core-01", "vendor": "frr",       "site": "DE-FRA"},
        {"hostname": "leaf2",          "vendor": "nokia_srl", "site": "CLAB-DC1"},
        {"hostname": "uk-lon-fw-01",   "vendor": "juniper",   "site": "UK-LON"},
        {"hostname": "spine2",         "vendor": "arista_eos","site": "CLAB-DC1"},
    ]}

    def test_frr_uses_show_running_config(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response(self._devices)), \
             patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"output": "..."})) as p:
            out = tools.get_config("de-fra-core-01")
        body = p.call_args.kwargs["json"]
        assert body["hostname"] == "de-fra-core-01"
        assert body["raw"] == "show running-config"
        assert out["vendor"] == "frr"
        assert out["command"] == "show running-config"

    def test_junos_uses_display_set(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response(self._devices)), \
             patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"output": "set …"})) as p:
            tools.get_config("uk-lon-fw-01")
        assert p.call_args.kwargs["json"]["raw"] == "show configuration | display set"

    def test_nokia_srl_uses_info(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response(self._devices)), \
             patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"output": "+ network-instance default"})) as p:
            tools.get_config("leaf2")
        assert p.call_args.kwargs["json"]["raw"] == "info"

    def test_arista_eos_uses_show_running_config(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response(self._devices)), \
             patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"output": "!"})) as p:
            tools.get_config("spine2")
        assert p.call_args.kwargs["json"]["raw"] == "show running-config"

    def test_section_is_appended(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response(self._devices)), \
             patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"output": "…"})) as p:
            tools.get_config("uk-lon-fw-01", section="protocols bgp")
        assert p.call_args.kwargs["json"]["raw"] == \
            "show configuration | display set protocols bgp"

    def test_unknown_hostname_returns_error_without_posting(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response(self._devices)), \
             patch("mcp_server.tools.requests.post") as p:
            out = tools.get_config("ghost-host-99")
        p.assert_not_called()
        assert "unknown hostname" in out["error"].lower()

    def test_hostname_lookup_is_case_insensitive(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response(self._devices)), \
             patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"output": "!"})):
            out = tools.get_config("DE-FRA-CORE-01")
        assert out["vendor"] == "frr"


# ─── Tools — closed-loop tier ───────────────────────────────────────────────


class TestHealthGateTools:
    def test_apply_posts_correct_body(self):
        with patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"job_id": "hg-1"})) as p:
            out = tools.health_gate_apply("de-fra-core-01", "<config/>", 10)
        body = p.call_args.kwargs["json"]
        assert body["hostname"] == "de-fra-core-01"
        assert body["timeout_s"] == 10
        assert out["job_id"] == "hg-1"

    def test_status_calls_correct_url(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response({"phase": "done"})) as p:
            tools.health_gate_status("hg-abc")
        assert "hg-abc" in p.call_args.args[0]


class TestRemediationTools:
    def test_propose_for_drift(self):
        drift = {"hostname": "x", "field": "ip", "sot": "1", "observed": "2"}
        with patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"proposal_id": "p-1"})) as p:
            out = tools.remediation_propose_for_drift(drift)
        assert p.call_args.kwargs["json"]["drift_row"] == drift
        assert out["proposal_id"] == "p-1"

    def test_approve_passes_actor(self):
        with patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"state": "executing"})) as p:
            tools.remediation_approve("p-1", actor="alice")
        body = p.call_args.kwargs["json"]
        assert body["actor"] == "alice"


class TestGait:
    def test_recent_actions_params(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response({"events": []})) as p:
            tools.gait_recent_actions(actor="mcp", limit=10)
        assert p.call_args.kwargs["params"] == {"limit": 10, "actor": "mcp"}


class TestPostmortemTools:
    def test_generate_passes_window(self):
        with patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"incident": {}, "markdown": "#"})) as p:
            tools.postmortem_generate(minutes_back=120,
                                      devices=["de-fra-core-01"])
        body = p.call_args.kwargs["json"]
        assert body["minutes_back"] == 120
        assert body["devices"] == ["de-fra-core-01"]

    def test_auto_detect_window(self):
        with patch("mcp_server.tools.requests.get",
                   return_value=_mock_response({"incidents": []})) as p:
            tools.postmortem_auto_detect(window_h=6)
        assert p.call_args.kwargs["params"] == {"window_h": 6}


class TestCompliance:
    def test_no_site_uses_lab_hostnames(self):
        with patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"results": []})) as p:
            tools.compliance_scan()
        body = p.call_args.kwargs["json"]
        assert "hostnames" in body
        assert "de-fra-core-01" in body["hostnames"]

    def test_with_site_uses_site_filter(self):
        with patch("mcp_server.tools.requests.post",
                   return_value=_mock_response({"results": []})) as p:
            tools.compliance_scan(site="de-fra")
        body = p.call_args.kwargs["json"]
        assert body == {"site": "de-fra"}


# ─── MCP server registration ────────────────────────────────────────────────


class TestServerRegistry:
    def _await(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro) if not asyncio.get_event_loop().is_running() else asyncio.run(coro)

    def test_fourteen_tools_registered(self):
        tools_list = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools_list}
        expected = {
            "list_devices", "bgp_status", "run_command", "get_config",
            "topology_snapshot", "compliance_scan",
            "health_gate_apply", "health_gate_status", "netbox_sot_drift",
            "remediation_propose_for_drift", "remediation_approve",
            "gait_recent_actions", "postmortem_auto_detect", "postmortem_generate",
        }
        assert expected.issubset(names)

    def test_resources_registered(self):
        resources = asyncio.run(mcp.list_resources())
        uris = {str(r.uri) for r in resources}
        assert "inventory://devices" in uris
        assert "topology://bgp" in uris
        assert "gait://recent" in uris
        assert "incidents://active" in uris

    def test_prompts_registered(self):
        prompts = asyncio.run(mcp.list_prompts())
        names = {p.name for p in prompts}
        assert "diagnose_device" in names
        assert "write_postmortem" in names

    def test_tool_has_description(self):
        tools_list = asyncio.run(mcp.list_tools())
        for t in tools_list:
            assert t.description, f"tool {t.name} missing description"

    def test_tool_schema_has_args(self):
        tools_list = asyncio.run(mcp.list_tools())
        by_name = {t.name: t for t in tools_list}
        # health_gate_apply requires hostname
        schema = by_name["health_gate_apply"].inputSchema
        assert "hostname" in schema.get("properties", {})

    def test_prompt_returns_string(self):
        # Render diagnose_device — should mention the hostname literally
        result = asyncio.run(mcp.get_prompt("diagnose_device", arguments={"hostname": "de-fra-core-01"}))
        # FastMCP wraps the return; just check it produced messages
        assert result.messages
        text = " ".join(
            (m.content.text if hasattr(m.content, "text") else str(m.content))
            for m in result.messages
        )
        assert "de-fra-core-01" in text


# ─── Configuration ──────────────────────────────────────────────────────────


class TestConfig:
    def test_api_base_uses_env(self, monkeypatch):
        monkeypatch.setenv("DCN_API_URL", "http://override:9999")
        # Reload the module to pick up the new env
        import importlib
        importlib.reload(tools)
        assert tools.API_BASE == "http://override:9999"
