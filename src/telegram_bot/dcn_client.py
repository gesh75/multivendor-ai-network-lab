"""
dcn_client.py — async HTTP client for the DCN Network Tool API.

The only component that touches the network. It mirrors the endpoint map already
used by ``mcp_dcn_server.py`` (same base URL convention, ``DCN_API_URL``), but is
async (httpx) to fit python-telegram-bot v20+'s event loop.

All transport/HTTP failures are normalised to ``DCNError`` so handlers can show a
friendly message instead of leaking a stack trace into a chat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class DCNError(Exception):
    """Raised when the DCN API is unreachable or returns a non-success status."""


@dataclass(frozen=True)
class DCNClient:
    """Async client over the DCN Flask API.

    ``client`` is injected so production code shares one pooled AsyncClient and
    tests can pass an httpx.MockTransport-backed client (no live server).
    """

    base_url: str
    client: httpx.AsyncClient
    timeout: float = 30.0
    ask_timeout: float = 120.0
    report_timeout: float = 300.0

    async def _get(self, path: str, params: dict | None = None,
                   timeout: float | None = None) -> Any:
        clean = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        try:
            resp = await self.client.get(
                f"{self.base_url}{path}", params=clean,
                timeout=timeout or self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise DCNError(f"{path} -> HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise DCNError(f"{path} -> {exc}") from exc

    async def _post(self, path: str, body: dict,
                    timeout: float | None = None) -> Any:
        try:
            resp = await self.client.post(
                f"{self.base_url}{path}", json=body,
                timeout=timeout or self.timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            raise DCNError(f"{path} -> HTTP {exc.response.status_code}") from exc
        except httpx.HTTPError as exc:
            raise DCNError(f"{path} -> {exc}") from exc

    # ── Read-only endpoints (Phase 1) ────────────────────────────────────────
    async def health(self) -> Any:
        return await self._get("/api/health")

    async def list_sites(self) -> Any:
        return await self._get("/api/sites")

    async def list_devices(self, site: str = "", role: str = "",
                           search: str = "") -> Any:
        return await self._get(
            "/api/devices", {"site": site, "role": role, "search": search}
        )

    async def topology(self) -> Any:
        return await self._get("/api/mv/topology")

    async def report_bgp(self, site: str = "") -> Any:
        return await self._get(
            "/api/report/bgp", {"site": site}, timeout=self.report_timeout
        )

    async def incident(self, ip: str, dtype: str = "junos") -> Any:
        return await self._post(
            "/api/incident", {"ip": ip, "dtype": dtype}, timeout=self.report_timeout
        )

    # ── LLM Q&A (Phase 2) ────────────────────────────────────────────────────
    async def ask(self, prompt: str) -> Any:
        """Route a free-text question through the Pydantic-AI orchestrator
        (which uses the local Qwen3 -> Claude fallback chain server-side)."""
        return await self._post(
            "/api/mv/orchestrator", {"prompt": prompt}, timeout=self.ask_timeout
        )
