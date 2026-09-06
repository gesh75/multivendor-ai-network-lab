"""
test_nornir.py — Tests for POST /api/nornir/run and nornir_engine module

Tests parallel multi-device task execution:
  - All tasks complete in parallel via ThreadPoolExecutor
  - Site filter correctly scopes targets
  - ok/warn/error classification from output
  - Result aggregation (counts + per-device details)
  - Edge cases: unknown site, unknown task, worker count cap

Two layers of tests:
  1. Unit tests of nornir_engine.py module directly (fast, no Flask overhead)
  2. Integration tests of the HTTP endpoint via test client
"""

import pytest
from unittest.mock import MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nornir_engine import (
    NORNIR_TASKS,
    _pick_command,
    _classify_output,
    _nornir_worker,
    nornir_run,
)
from tests.conftest import LAB_DEVICES, BGP_SUMMARY_OUTPUT, BGP_SUMMARY_WITH_DOWN


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests — nornir_engine module
# ═══════════════════════════════════════════════════════════════════════════════

class TestPickCommand:
    """_pick_command selects correct vendor CLI."""

    def test_frr_uses_frr_command(self):
        task = NORNIR_TASKS["bgp_health"]
        assert _pick_command(task, "frr") == task["cmd_frr"]

    def test_eos_uses_eos_command(self):
        task = NORNIR_TASKS["bgp_health"]
        assert _pick_command(task, "eos") == task["cmd_eos"]

    def test_junos_uses_junos_command(self):
        task = NORNIR_TASKS["bgp_health"]
        assert _pick_command(task, "junos") == task["cmd_junos"]

    def test_unknown_dtype_falls_back_to_junos(self):
        task = NORNIR_TASKS["bgp_health"]
        assert _pick_command(task, "unknown") == task["cmd_junos"]


class TestClassifyOutput:
    """_classify_output heuristic status detection."""

    def test_ok_on_normal_bgp_output(self):
        assert _classify_output(BGP_SUMMARY_OUTPUT, True) == "ok"

    def test_warn_on_bgp_active_state(self):
        assert _classify_output(BGP_SUMMARY_WITH_DOWN, True) == "warn"

    def test_warn_on_alarm_keyword(self):
        assert _classify_output("MAJOR alarm: link down on xe-0/0/0", True) == "warn"

    def test_warn_on_error_keyword(self):
        assert _classify_output("error: interface xe-0/0/1 not found", True) == "warn"

    def test_error_on_connection_refused(self):
        assert _classify_output("Connection refused to 10.0.0.1", True) == "error"

    def test_error_when_success_false(self):
        assert _classify_output("anything", False) == "error"

    def test_error_on_empty_output(self):
        assert _classify_output("", True) == "error"

    def test_error_on_very_short_output(self):
        assert _classify_output("ok", True) == "error"  # < 10 chars


class TestNornirWorker:
    """_nornir_worker per-device SSH execution."""

    def test_worker_returns_ok_on_success(self):
        run_fn = MagicMock(return_value={"success": True, "output": BGP_SUMMARY_OUTPUT, "command": "show bgp summary"})
        dev = LAB_DEVICES[0]
        result = _nornir_worker(dev, "show bgp summary", run_fn)

        assert result["hostname"] == "de-fra-core-01"
        assert result["status"] == "ok"
        assert result["elapsed"] >= 0
        run_fn.assert_called_once()

    def test_worker_returns_warn_on_bgp_down(self):
        run_fn = MagicMock(return_value={"success": True, "output": BGP_SUMMARY_WITH_DOWN, "command": "show bgp summary"})
        result = _nornir_worker(LAB_DEVICES[0], "show bgp summary", run_fn)
        assert result["status"] == "warn"

    def test_worker_returns_error_on_ssh_failure(self):
        run_fn = MagicMock(return_value={"success": False, "output": "Connection refused", "command": "show bgp summary"})
        result = _nornir_worker(LAB_DEVICES[0], "show bgp summary", run_fn)
        assert result["status"] == "error"

    def test_worker_returns_error_on_exception(self):
        run_fn = MagicMock(side_effect=Exception("SSH timeout"))
        result = _nornir_worker(LAB_DEVICES[0], "show bgp summary", run_fn)
        assert result["status"] == "error"
        assert "SSH timeout" in result["output"]

    def test_worker_includes_hostname(self):
        run_fn = MagicMock(return_value={"success": True, "output": BGP_SUMMARY_OUTPUT, "command": "x"})
        result = _nornir_worker(LAB_DEVICES[2], "show bgp summary", run_fn)
        assert result["hostname"] == "uk-lon-core-01"

    def test_worker_records_elapsed_time(self):
        run_fn = MagicMock(return_value={"success": True, "output": BGP_SUMMARY_OUTPUT, "command": "x"})
        result = _nornir_worker(LAB_DEVICES[0], "show bgp summary", run_fn)
        assert isinstance(result["elapsed"], float)
        assert result["elapsed"] >= 0


class TestNornirRun:
    """nornir_run orchestration — parallel execution and aggregation."""

    def _make_run_fn(self, output: str = BGP_SUMMARY_OUTPUT, success: bool = True):
        return MagicMock(return_value={"success": success, "output": output, "command": "show bgp summary"})

    def test_all_devices_targeted_when_no_site_filter(self):
        run_fn = self._make_run_fn()
        result = nornir_run(LAB_DEVICES, "bgp_health", site_filter="", run_fn=run_fn)
        assert result["devices"] == len(LAB_DEVICES)
        assert len(result["results"]) == len(LAB_DEVICES)

    def test_site_filter_de_fra_returns_site_devices(self):
        run_fn = self._make_run_fn()
        result = nornir_run(LAB_DEVICES, "bgp_health", site_filter="DE-FRA", run_fn=run_fn)
        expected = sum(1 for d in LAB_DEVICES if d["site"].upper() == "DE-FRA")
        assert result["devices"] == expected

    def test_site_filter_uk_lon_returns_site_devices(self):
        run_fn = self._make_run_fn()
        result = nornir_run(LAB_DEVICES, "bgp_health", site_filter="UK-LON", run_fn=run_fn)
        expected = sum(1 for d in LAB_DEVICES if d["site"].upper() == "UK-LON")
        assert result["devices"] == expected

    def test_site_filter_case_insensitive(self):
        run_fn = self._make_run_fn()
        result_upper = nornir_run(LAB_DEVICES, "bgp_health", site_filter="DE-FRA", run_fn=run_fn)
        result_lower = nornir_run(LAB_DEVICES, "bgp_health", site_filter="de-fra", run_fn=run_fn)
        assert result_upper["devices"] == result_lower["devices"]

    def test_unknown_site_raises_value_error(self):
        run_fn = self._make_run_fn()
        with pytest.raises(ValueError, match="No devices found"):
            nornir_run(LAB_DEVICES, "bgp_health", site_filter="FAKESIT", run_fn=run_fn)

    def test_unknown_task_raises_value_error(self):
        run_fn = self._make_run_fn()
        with pytest.raises(ValueError, match="Unknown task"):
            nornir_run(LAB_DEVICES, "nonexistent_task", run_fn=run_fn)

    def test_workers_capped_at_200(self):
        run_fn = self._make_run_fn()
        result = nornir_run(LAB_DEVICES, "bgp_health", workers=99999, run_fn=run_fn)
        assert result["workers"] <= 200

    def test_workers_capped_at_device_count(self):
        run_fn = self._make_run_fn()
        result = nornir_run(LAB_DEVICES, "bgp_health", workers=100, run_fn=run_fn)
        assert result["workers"] <= len(LAB_DEVICES)

    def test_ok_count_aggregation(self):
        run_fn = self._make_run_fn(output=BGP_SUMMARY_OUTPUT, success=True)
        result = nornir_run(LAB_DEVICES, "bgp_health", run_fn=run_fn)
        assert result["ok"] + result["warn"] + result["error"] == result["devices"]

    def test_warn_count_when_bgp_down(self):
        run_fn = self._make_run_fn(output=BGP_SUMMARY_WITH_DOWN)
        result = nornir_run(LAB_DEVICES, "bgp_health", run_fn=run_fn)
        assert result["warn"] >= 1

    def test_result_contains_per_device_entries(self):
        run_fn = self._make_run_fn()
        result = nornir_run(LAB_DEVICES, "bgp_health", run_fn=run_fn)
        for r in result["results"]:
            assert "hostname" in r
            assert "status" in r
            assert "output" in r
            assert "elapsed" in r

    def test_elapsed_time_is_non_negative(self):
        run_fn = self._make_run_fn()
        result = nornir_run(LAB_DEVICES, "bgp_health", run_fn=run_fn)
        assert result["elapsed"] >= 0  # mocked run_fn is sub-millisecond → may round to 0.0

    def test_task_label_in_response(self):
        run_fn = self._make_run_fn()
        result = nornir_run(LAB_DEVICES, "bgp_health", run_fn=run_fn)
        assert result["task"] == NORNIR_TASKS["bgp_health"]["label"]

    def test_run_fn_required(self):
        with pytest.raises((ValueError, TypeError)):
            nornir_run(LAB_DEVICES, "bgp_health")  # no run_fn

    def test_all_task_types_work(self):
        """All 6 defined tasks execute without error."""
        run_fn = self._make_run_fn()
        for task_name in NORNIR_TASKS:
            result = nornir_run(LAB_DEVICES, task_name, run_fn=run_fn)
            assert result["devices"] == len(LAB_DEVICES)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration tests — HTTP endpoint
# ═══════════════════════════════════════════════════════════════════════════════

class TestNornirEndpoint:
    """POST /api/nornir/run via Flask test client."""

    def test_bgp_health_all_devices(self, app_client, mock_ssh):
        """Default task runs across the conftest lab inventory."""
        mock_ssh.return_value = {"success": True, "output": BGP_SUMMARY_OUTPUT, "command": "show bgp summary"}

        resp = app_client.post("/api/nornir/run", json={"task": "bgp_health", "workers": 6})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["devices"] == len(LAB_DEVICES)
        assert data["ok"] + data["warn"] + data["error"] == len(LAB_DEVICES)

    def test_site_filter_de_fra(self, app_client, mock_ssh):
        """DE-FRA site filter returns only DE-FRA devices."""
        mock_ssh.return_value = {"success": True, "output": BGP_SUMMARY_OUTPUT, "command": "show bgp summary"}

        resp = app_client.post("/api/nornir/run", json={"task": "bgp_health", "site": "DE-FRA"})
        assert resp.status_code == 200
        data = resp.get_json()
        expected = sum(1 for d in LAB_DEVICES if d["site"].upper() == "DE-FRA")
        assert data["devices"] == expected
        hostnames = [r["hostname"] for r in data["results"]]
        assert all("de-fra" in h for h in hostnames)

    def test_unknown_site_returns_404(self, app_client):
        resp = app_client.post("/api/nornir/run", json={"task": "bgp_health", "site": "MARS1"})
        assert resp.status_code == 404

    def test_default_task_is_bgp_health(self, app_client, mock_ssh):
        """Omitting task defaults to bgp_health."""
        mock_ssh.return_value = {"success": True, "output": BGP_SUMMARY_OUTPUT, "command": "show bgp summary"}

        resp = app_client.post("/api/nornir/run", json={})
        assert resp.status_code == 200
        data = resp.get_json()
        assert "BGP" in data["task"]

    def test_response_schema(self, app_client, mock_ssh):
        """Response always contains all required keys."""
        mock_ssh.return_value = {"success": True, "output": BGP_SUMMARY_OUTPUT, "command": "x"}

        resp = app_client.post("/api/nornir/run", json={"task": "version"})
        assert resp.status_code == 200
        data = resp.get_json()
        for key in ("task", "site", "devices", "workers", "elapsed", "ok", "warn", "error", "results"):
            assert key in data, f"Missing key: {key}"

    def test_elapsed_is_positive(self, app_client, mock_ssh):
        mock_ssh.return_value = {"success": True, "output": BGP_SUMMARY_OUTPUT, "command": "x"}
        resp = app_client.post("/api/nornir/run", json={"task": "bgp_health"})
        data = resp.get_json()
        assert data["elapsed"] >= 0

    def test_workers_respected(self, app_client, mock_ssh):
        mock_ssh.return_value = {"success": True, "output": BGP_SUMMARY_OUTPUT, "command": "x"}
        resp = app_client.post("/api/nornir/run", json={"task": "bgp_health", "workers": 2})
        data = resp.get_json()
        assert data["workers"] <= 2

    def test_interface_check_task(self, app_client, mock_ssh):
        mock_ssh.return_value = {"success": True, "output": "eth0: up\neth1: up\n", "command": "x"}
        resp = app_client.post("/api/nornir/run", json={"task": "interface_check"})
        assert resp.status_code == 200
        assert "Interface" in resp.get_json()["task"]
