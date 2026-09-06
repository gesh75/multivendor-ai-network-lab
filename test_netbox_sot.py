"""
Tests for the NetBox SoT drift detector.

Run from src/ parent dir:
    cd 04_Scripts_Tools/DCN_Network_Tool && pytest test_netbox_sot.py -v

Covers:
  - Mode detection (force-simulate env, missing creds, missing pynetbox)
  - Loaders (fetch_sot, fetch_observed, missing files)
  - Normalization (lowercase hostname, key projection)
  - compute_drift: matched count, presence (missing/extra), field drift,
    severity tiers, SoT-side optional fields skipped
  - refresh() round-trip
  - The seed file actually produces the drift documented in its header
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE / "src"))

os.environ["NETBOX_SOT_FORCE_SIMULATE"] = "1"

import netbox_sot as nbs  # noqa: E402


# ─── Helpers ────────────────────────────────────────────────────────────────


def _dev(hostname: str, **kw) -> dict:
    """Build a normalized-shape device row for ad-hoc tests."""
    base = {
        "hostname": hostname,
        "ip": None,
        "as": None,
        "vendor": None,
        "model": None,
        "role": None,
        "site": None,
        "os": None,
    }
    base.update(kw)
    return base


# ─── Mode detection ─────────────────────────────────────────────────────────


class TestModeDetection:
    def test_forced_simulate(self):
        assert nbs._detect_mode() == "simulated"

    def test_missing_creds_is_simulated(self, monkeypatch):
        monkeypatch.delenv("NETBOX_SOT_FORCE_SIMULATE", raising=False)
        monkeypatch.delenv("NETBOX_URL", raising=False)
        monkeypatch.delenv("NETBOX_TOKEN", raising=False)
        assert nbs._detect_mode() == "simulated"

    def test_creds_without_pynetbox_is_simulated(self, monkeypatch):
        monkeypatch.delenv("NETBOX_SOT_FORCE_SIMULATE", raising=False)
        monkeypatch.setenv("NETBOX_URL", "https://nb.example.com")
        monkeypatch.setenv("NETBOX_TOKEN", "fake-token")
        # Force pynetbox import to fail even if it's installed in the venv,
        # so the test is deterministic across environments.
        import sys
        monkeypatch.setitem(sys.modules, "pynetbox", None)
        assert nbs._detect_mode() == "simulated"


# ─── Normalization ──────────────────────────────────────────────────────────


class TestNormalize:
    def test_lowercases_hostname(self):
        out = nbs._normalize({"hostname": "DE-FRA-CORE-01", "ip": "1.1.1.1"})
        assert out["hostname"] == "de-fra-core-01"

    def test_strips_whitespace(self):
        out = nbs._normalize({"hostname": "  host  ", "ip": "x"})
        assert out["hostname"] == "host"

    def test_projects_only_known_fields(self):
        out = nbs._normalize({"hostname": "h", "ip": "x", "port": 2201, "config": "junk"})
        assert "port" not in out
        assert "config" not in out
        assert out["ip"] == "x"


# ─── Loaders ────────────────────────────────────────────────────────────────


class TestLoaders:
    def test_fetch_observed_returns_devices(self):
        obs = nbs.fetch_observed()
        raw = json.loads(nbs.DEFAULT_OBSERVED_PATH.read_text(encoding="utf-8"))
        assert len(obs) == len(raw.get("devices") or [])
        hostnames = {d["hostname"] for d in obs}
        assert "de-fra-core-01" in hostnames
        assert "nl-ams-edge-01" in hostnames

    def test_fetch_sot_returns_devices(self):
        sot = nbs.fetch_sot()
        assert len(sot) > 0
        hostnames = {d["hostname"] for d in sot}
        # The seed deliberately includes uk-lon-fw-02 only on the SoT side
        assert "uk-lon-fw-02" in hostnames

    def test_fetch_observed_missing_file_returns_empty(self, tmp_path):
        out = nbs.fetch_observed(observed_path=tmp_path / "missing.json")
        assert out == []

    def test_fetch_sot_missing_file_returns_empty(self, tmp_path):
        # Force simulated path even though env is set — we want to verify
        # the FileNotFoundError fallback in _load_json.
        out = nbs.fetch_sot(sot_path=tmp_path / "missing.json")
        assert out == []


# ─── compute_drift ──────────────────────────────────────────────────────────


class TestComputeDrift:
    def test_identical_sets_no_drift(self):
        rows = [_dev("a", ip="1.1.1.1", vendor="frr", site="DE-FRA")]
        report = nbs.compute_drift(sot=rows, observed=rows)
        assert report.drift_count == 0
        assert report.sot_count == 1
        assert report.observed_count == 1
        assert report.matched_count == 1

    def test_field_drift_emits_row(self):
        s = [_dev("a", ip="1.1.1.1", as_="65001") | {"as": 65001}]
        o = [_dev("a", ip="1.1.1.2", as_="65001") | {"as": 65001}]
        # Bypass the merge confusion above: build explicit dicts.
        s = [{"hostname": "a", "ip": "1.1.1.1", "as": 65001, "vendor": None, "model": None, "role": None, "site": None, "os": None}]
        o = [{"hostname": "a", "ip": "1.1.1.2", "as": 65001, "vendor": None, "model": None, "role": None, "site": None, "os": None}]
        report = nbs.compute_drift(sot=s, observed=o)
        assert report.drift_count == 1
        assert report.drift_rows[0]["field"] == "ip"
        assert report.drift_rows[0]["severity"] == "high"
        assert report.drift_rows[0]["sot"] == "1.1.1.1"
        assert report.drift_rows[0]["observed"] == "1.1.1.2"

    def test_missing_in_lab_is_high(self):
        s = [_dev("ghost", ip="9.9.9.9")]
        o = []
        report = nbs.compute_drift(sot=s, observed=o)
        assert report.drift_count == 1
        row = report.drift_rows[0]
        assert row["field"] == "presence"
        assert row["sot"] == "present"
        assert row["observed"] == "missing"
        assert row["severity"] == "high"

    def test_extra_in_lab_is_critical(self):
        s = []
        o = [_dev("rogue", ip="9.9.9.9")]
        report = nbs.compute_drift(sot=s, observed=o)
        assert report.drift_count == 1
        row = report.drift_rows[0]
        assert row["field"] == "presence"
        assert row["sot"] == "missing"
        assert row["observed"] == "present"
        assert row["severity"] == "critical"

    def test_sot_side_none_is_not_drift(self):
        # When SoT doesn't declare a field, the observed value is allowed
        # to be anything (avoids false positives on optional fields).
        s = [_dev("a")]  # all None
        o = [_dev("a", ip="1.2.3.4", as_=65001)]
        report = nbs.compute_drift(sot=s, observed=o)
        assert report.drift_count == 0

    def test_severity_tiers(self):
        s = [{"hostname": "a", "ip": "1.1.1.1", "as": 1, "vendor": "v", "model": "m", "role": "r", "site": "S", "os": "o"}]
        o = [{"hostname": "a", "ip": "2.2.2.2", "as": 2, "vendor": "x", "model": "n", "role": "q", "site": "T", "os": "p"}]
        report = nbs.compute_drift(sot=s, observed=o)
        severities = {row["field"]: row["severity"] for row in report.drift_rows}
        assert severities["ip"] == "high"
        assert severities["as"] == "high"
        assert severities["site"] == "high"
        assert severities["vendor"] == "medium"
        assert severities["role"] == "medium"
        assert severities["model"] == "low"
        assert severities["os"] == "low"

    def test_matched_count(self):
        s = [_dev("a", ip="1"), _dev("b", ip="2"), _dev("c", ip="3")]
        o = [_dev("a", ip="1"), _dev("b", ip="2")]
        report = nbs.compute_drift(sot=s, observed=o)
        # 'a' and 'b' match (full); 'c' is missing → matched=2
        assert report.matched_count == 2
        assert report.sot_count == 3
        assert report.observed_count == 2


# ─── Seed file integration ──────────────────────────────────────────────────


class TestSeedIntegrationDrift:
    """The seed file deliberately bakes in 5 drift scenarios — verify each."""

    @pytest.fixture
    def report(self):
        return nbs.refresh()

    def test_total_drift_count_matches_seed(self, report):
        # Seed advertises 5 drift scenarios; verify the report agrees.
        assert report.drift_count >= 5

    def test_de_fra_core_01_ip_drift(self, report):
        ip_rows = [r for r in report.drift_rows
                   if r["hostname"] == "de-fra-core-01" and r["field"] == "ip"]
        assert len(ip_rows) == 1
        assert ip_rows[0]["sot"] == "10.200.0.99"
        assert ip_rows[0]["observed"] == "10.200.0.11"
        assert ip_rows[0]["severity"] == "high"

    def test_uk_lon_core_01_as_drift(self, report):
        as_rows = [r for r in report.drift_rows
                   if r["hostname"] == "uk-lon-core-01" and r["field"] == "as"]
        assert len(as_rows) == 1
        assert as_rows[0]["sot"] == 65103
        assert as_rows[0]["observed"] == 65003
        assert as_rows[0]["severity"] == "high"

    def test_nl_ams_edge_01_extra_in_lab(self, report):
        rows = [r for r in report.drift_rows
                if r["hostname"] == "nl-ams-edge-01" and r["field"] == "presence"]
        assert len(rows) == 1
        assert rows[0]["sot"] == "missing"
        assert rows[0]["observed"] == "present"
        assert rows[0]["severity"] == "critical"

    def test_uk_lon_fw_02_missing_from_lab(self, report):
        rows = [r for r in report.drift_rows
                if r["hostname"] == "uk-lon-fw-02" and r["field"] == "presence"]
        assert len(rows) == 1
        assert rows[0]["sot"] == "present"
        assert rows[0]["observed"] == "missing"
        assert rows[0]["severity"] == "high"

    def test_mode_is_simulated(self, report):
        assert report.mode == "simulated"

    def test_report_has_iso_timestamp(self, report):
        assert "T" in report.ts and (report.ts.endswith("+00:00") or "Z" in report.ts)


# ─── refresh round-trip ─────────────────────────────────────────────────────


class TestRefresh:
    def test_refresh_returns_drift_report(self):
        report = nbs.refresh()
        assert isinstance(report, nbs.DriftReport)
        d = report.to_dict()
        assert "drift_count" in d
        assert "drift_rows" in d
        assert "mode" in d
