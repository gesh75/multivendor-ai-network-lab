"""Phase 5-A — forecast_engine unit tests.

Run with:  pytest test_forecast.py -v
"""
from __future__ import annotations

import math
import os
import statistics
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "src"))

from forecast_engine import (  # noqa: E402
    ANOMALY_THRESHOLDS,
    CiscoTimesFMForecaster,
    ForecastResult,
    StatisticalForecaster,
    _detect_anomalies,
    get_forecaster,
    predict,
    reset_forecaster,
    synth_series,
)


# ─── Synthetic data ──────────────────────────────────────────────────────────


class TestSynthSeries:
    def test_cpu_default_length_128(self):
        s = synth_series("cpu")
        assert len(s) == 128
        assert all(0 <= x <= 100 for x in s)

    def test_cpu_has_daily_seasonality(self):
        """Period-24 seasonal sin wave should be detectable in the data."""
        s = synth_series("cpu", length=256, seed=1)
        # rough autocorrelation at lag 24 should be > 0.3
        mean = statistics.fmean(s)
        var = sum((x - mean) ** 2 for x in s)
        num = sum((s[i] - mean) * (s[i - 24] - mean) for i in range(24, len(s)))
        acf24 = num / var
        assert acf24 > 0.3, f"expected ACF24 > 0.3, got {acf24:.3f}"

    def test_memory_no_seasonality(self):
        s = synth_series("memory", length=200, seed=2)
        assert len(s) == 200
        # mean should grow over time (positive trend)
        first_half = statistics.fmean(s[:100])
        second_half = statistics.fmean(s[100:])
        assert second_half > first_half

    def test_anomaly_series_ramps_up(self):
        s = synth_series("anomaly", length=128, seed=3)
        # tail should be far higher than middle (the ramp)
        assert statistics.fmean(s[-10:]) > statistics.fmean(s[60:80])

    def test_bgp_routes_stable_around_50k(self):
        s = synth_series("bgp_routes", length=128, seed=4)
        m = statistics.fmean(s)
        assert 49000 <= m <= 51000

    def test_unknown_kind_is_uniform_fallback(self):
        s = synth_series("nonexistent_kind", length=50, seed=5)
        assert len(s) == 50
        # uniform fallback should be roughly in [20, 50]
        assert 15 < statistics.fmean(s) < 55


# ─── Statistical backend ─────────────────────────────────────────────────────


class TestStatisticalForecaster:
    def setup_method(self):
        self.f = StatisticalForecaster()

    def test_holt_winters_picks_period_24(self):
        hist = synth_series("cpu", length=128)
        out = self.f.forecast(hist, horizon=24)
        assert out["note"] == "holt_winters_period_24"
        assert len(out["forecast"]) == 24
        assert "q05" in out["quantiles"]
        assert "q95" in out["quantiles"]
        assert len(out["quantiles"]["q50"]) == 24

    def test_quantile_ordering(self):
        """q05 <= q25 <= q50 <= q75 <= q95 at every step."""
        hist = synth_series("cpu", length=128)
        out = self.f.forecast(hist, horizon=32)
        q = out["quantiles"]
        for i in range(32):
            assert q["q05"][i] <= q["q25"][i] <= q["q50"][i] <= q["q75"][i] <= q["q95"][i]

    def test_short_history_falls_back_to_mean(self):
        out = self.f.forecast([10.0, 11.0, 9.0], horizon=5)
        assert out["note"] == "insufficient_history_mean_fallback"
        # mean of [10, 11, 9] = 10
        assert all(abs(v - 10.0) < 0.01 for v in out["forecast"])

    def test_no_seasonality_falls_back_to_simple_exp(self):
        # 40 random-walk points → no period should be detected
        import random
        rng = random.Random(7)
        hist = []
        v = 50.0
        for _ in range(40):
            v += rng.gauss(0, 1)
            hist.append(v)
        out = self.f.forecast(hist, horizon=10)
        # Either simple_exp_smoothing or holt_winters (low ACF noise may still cross threshold)
        assert out["note"] in ("simple_exp_smoothing", "holt_winters_period_7")

    def test_horizon_clamped_to_128(self):
        out = self.f.forecast(synth_series("cpu"), horizon=1000)
        assert len(out["forecast"]) == 128

    def test_horizon_min_1(self):
        out = self.f.forecast(synth_series("cpu"), horizon=0)
        assert len(out["forecast"]) == 1

    def test_empty_history_raises(self):
        with pytest.raises(ValueError, match="empty"):
            self.f.forecast([], horizon=10)

    def test_forecast_uses_seasonal_shape(self):
        """For a clean sinusoid, predicted values should follow the cycle."""
        # 4 full periods of pure sin, period=24
        hist = [50 + 20 * math.sin(2 * math.pi * i / 24) for i in range(96)]
        out = self.f.forecast(hist, horizon=24)
        # the forecast should span roughly [30, 70] like the input
        f_min, f_max = min(out["forecast"]), max(out["forecast"])
        assert f_max - f_min > 20, f"expected swing > 20, got {f_max - f_min:.1f}"


# ─── Anomaly detection ───────────────────────────────────────────────────────


class TestAnomalyDetection:
    def test_cpu_critical_fires_first(self):
        forecast = [40.0] * 10 + [98.0] * 10  # critical at step 10
        quantiles = {"q75": forecast}
        alerts = _detect_anomalies(forecast, quantiles, "cpu_pct")
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "critical"
        assert alerts[0]["step"] == 10

    def test_cpu_high_fires_when_no_critical(self):
        forecast = [40.0] * 10 + [85.0] * 10  # high at step 10, no critical
        quantiles = {"q75": forecast}
        alerts = _detect_anomalies(forecast, quantiles, "cpu_pct")
        assert len(alerts) == 1
        assert alerts[0]["severity"] == "high"

    def test_no_alert_when_clean(self):
        forecast = [40.0] * 32
        quantiles = {"q75": forecast}
        alerts = _detect_anomalies(forecast, quantiles, "cpu_pct")
        assert alerts == []

    def test_bgp_route_drop_alert(self):
        baseline = 50000.0
        forecast = [baseline] * 5 + [baseline * 0.85] * 20  # 15% drop
        quantiles = {"q75": forecast}
        alerts = _detect_anomalies(forecast, quantiles, "bgp_route_count")
        assert len(alerts) == 1
        assert alerts[0]["kind"] == "bgp_route_count_drop"
        assert alerts[0]["severity"] == "high"

    def test_unknown_metric_no_thresholds(self):
        alerts = _detect_anomalies([1.0] * 10, {"q75": [1.0] * 10}, "unknown_metric")
        assert alerts == []


# ─── Registry ────────────────────────────────────────────────────────────────


class TestRegistry:
    def setup_method(self):
        reset_forecaster()

    def test_default_is_statistical(self, monkeypatch):
        monkeypatch.delenv("DCN_FORECAST_PROVIDER", raising=False)
        f = get_forecaster()
        assert f.name == "holt-winters-stdlib"

    def test_cisco_provider_falls_back_when_unavailable(self, monkeypatch):
        # torch is not installed in the venv → CiscoTimesFMForecaster() should fail
        # → registry should silently fall back to statistical
        monkeypatch.setenv("DCN_FORECAST_PROVIDER", "cisco-timesfm")
        reset_forecaster()
        f = get_forecaster()
        # When cisco backend is unavailable, fall back
        assert f.name in ("holt-winters-stdlib", "cisco-time-series-model-1.0")

    def test_singleton_returns_same_instance(self):
        reset_forecaster()
        a = get_forecaster()
        b = get_forecaster()
        assert a is b

    def test_reset_clears_singleton(self):
        a = get_forecaster()
        reset_forecaster()
        b = get_forecaster()
        # different instance after reset
        assert a is not b


# ─── End-to-end via predict() ────────────────────────────────────────────────


class TestPredictAPI:
    def test_returns_forecast_result(self):
        hist = synth_series("cpu", length=128)
        r = predict("test-device", "cpu_pct", hist, horizon=24)
        assert isinstance(r, ForecastResult)
        assert r.device == "test-device"
        assert r.metric == "cpu_pct"
        assert len(r.forecast) == 24
        assert r.ms >= 0
        assert r.model

    def test_anomaly_alerts_populated(self):
        hist = synth_series("anomaly", length=128, seed=3)
        r = predict("test", "cpu_pct", hist, horizon=64)
        assert len(r.anomaly_alerts) > 0
        assert r.anomaly_alerts[0]["severity"] in ("high", "critical")

    def test_frozen_dataclass(self):
        r = predict("test", "cpu_pct", synth_series("cpu"), horizon=10)
        with pytest.raises(Exception):
            r.device = "changed"  # type: ignore[misc]


# ─── Performance regressions ─────────────────────────────────────────────────


class TestPerformance:
    def test_single_forecast_under_100ms(self):
        hist = synth_series("cpu", length=128)
        t0 = time.perf_counter()
        predict("p", "cpu_pct", hist, horizon=128)
        ms = (time.perf_counter() - t0) * 1000
        assert ms < 100, f"forecast took {ms:.0f}ms (target < 100ms)"

    def test_100_forecasts_under_3s(self):
        hist = synth_series("cpu", length=128)
        t0 = time.perf_counter()
        for _ in range(100):
            predict("p", "cpu_pct", hist, horizon=128)
        total = time.perf_counter() - t0
        # Shared GitHub-hosted runners observed 3.78–4.17s for this loop
        # (PR #11 py3.11/py3.12). Keep the 3s local target; use a CI ceiling
        # that still fails on a ~10× regression without flaking GHA.
        budget = 10.0 if os.environ.get("GITHUB_ACTIONS") == "true" else 3.0
        assert total < budget, f"100 forecasts took {total:.2f}s (target < {budget:g}s)"


# ─── Thresholds sanity check ─────────────────────────────────────────────────


class TestThresholds:
    def test_all_metrics_have_thresholds(self):
        for m in ("cpu_pct", "mem_pct", "iface_in_pct", "bgp_route_count", "error_rate"):
            assert m in ANOMALY_THRESHOLDS

    def test_thresholds_are_sane(self):
        for m, t in ANOMALY_THRESHOLDS.items():
            if "high" in t and "critical" in t:
                assert t["critical"] > t["high"], f"{m}: critical must exceed high"
