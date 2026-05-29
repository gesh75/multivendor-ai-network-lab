"""
test_tg_formatting.py — Telegram ChatOps bot: API-JSON -> chat-message renderers.

Pure functions that turn DCN API payloads into Telegram-safe text. They must:
  - never exceed Telegram's 4096-char message limit (truncate),
  - tolerate missing/partial fields (defensive .get usage),
  - degrade to a readable generic render for endpoints whose schema we don't pin.
"""

from telegram_bot.formatting import (
    TELEGRAM_MAX,
    truncate,
    format_health,
    format_sites,
    format_devices,
    format_ask,
    format_report,
    format_error,
)


class TestTruncate:
    def test_short_text_unchanged(self):
        assert truncate("hello", 100) == "hello"

    def test_long_text_truncated_within_limit(self):
        out = truncate("x" * 5000, 100)
        assert len(out) <= 100
        assert out.endswith("…")

    def test_default_limit_is_telegram_max(self):
        assert len(truncate("y" * 10000)) <= TELEGRAM_MAX


class TestFormatHealth:
    def test_ok_status_and_device_count(self):
        out = format_health(
            {"status": "ok", "devices_loaded": 10, "timestamp": "2026-05-29T11:00:00"}
        )
        assert "ok" in out.lower()
        assert "10" in out

    def test_missing_fields_safe(self):
        out = format_health({})
        assert isinstance(out, str) and out.strip()


class TestFormatSites:
    def test_plain_list(self):
        out = format_sites(["DE-FRA", "UK-LON"])
        assert "DE-FRA" in out and "UK-LON" in out

    def test_wrapped_in_dict(self):
        out = format_sites({"sites": ["NL-AMS"]})
        assert "NL-AMS" in out

    def test_empty_is_string(self):
        assert isinstance(format_sites([]), str)


class TestFormatDevices:
    SAMPLE = [
        {"hostname": "de-fra-core-01", "site": "DE-FRA", "type": "frr", "ip": "10.0.0.1"},
        {"hostname": "uk-lon-core-01", "site": "UK-LON", "type": "frr", "ip": "10.0.0.2"},
    ]

    def test_lists_hostnames(self):
        out = format_devices(self.SAMPLE)
        assert "de-fra-core-01" in out and "uk-lon-core-01" in out

    def test_respects_limit_and_reports_overflow(self):
        many = [{"hostname": f"h{i}"} for i in range(100)]
        out = format_devices(many, limit=10)
        assert "h0" in out and "h9" in out
        assert "h99" not in out
        assert "90 more" in out

    def test_wrapped_in_dict(self):
        out = format_devices({"devices": self.SAMPLE})
        assert "de-fra-core-01" in out


class TestFormatAsk:
    def test_prefers_rendered_field(self):
        out = format_ask({"rendered": "All BGP peers up.", "agent": "IncidentAgent"})
        assert "All BGP peers up." in out

    def test_falls_back_to_output(self):
        assert "hi there" in format_ask({"output": "hi there"})

    def test_error_payload(self):
        assert "prompt required" in format_ask({"error": "prompt required"})


class TestFormatReport:
    def test_dict_renders_values(self):
        out = format_report("BGP sessions", {"total_peers": 36, "down_sessions": 0})
        assert "BGP sessions" in out and "36" in out

    def test_error_dict(self):
        out = format_report("BGP sessions", {"error": "backend down"})
        assert "backend down" in out

    def test_list_payload(self):
        out = format_report("Topology", [{"node": "a"}])
        assert "Topology" in out


class TestFormatError:
    def test_contains_message(self):
        assert "device unreachable" in format_error("device unreachable")


class TestTruncateEdges:
    def test_limit_zero_returns_empty(self):
        assert truncate("hello", 0) == ""

    def test_limit_one_no_ellipsis(self):
        out = truncate("hello", 1)
        assert out == "h"
        assert "…" not in out


class TestErrorDetection:
    """Sourcery #1: falsy error values (""/0) must still be flagged as errors."""

    def test_empty_string_error_is_flagged(self):
        out = format_health({"error": ""})
        assert out.startswith("⚠️")  # error path, not normal render

    def test_zero_error_is_flagged(self):
        out = format_sites({"error": 0})
        assert out.startswith("⚠️")

    def test_devices_error_is_flagged(self):
        out = format_devices({"error": "boom"})
        assert out.startswith("⚠️") and "boom" in out
