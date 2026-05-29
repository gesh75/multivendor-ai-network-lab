"""
formatting.py — render DCN API JSON into Telegram-safe message text.

Pure functions only. Every renderer must stay under Telegram's 4096-char limit and
tolerate partial/missing fields, because the upstream API shapes vary by endpoint
and we never want a malformed payload to crash a handler.
"""

from __future__ import annotations

import json
from typing import Any

TELEGRAM_MAX = 4096


def truncate(text: str, limit: int = TELEGRAM_MAX) -> str:
    """Clip text to ``limit`` chars, appending an ellipsis when clipped."""
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:limit]
    return text[: limit - 1] + "…"


def format_error(message: str) -> str:
    return f"⚠️ {message}"


def _is_error(data: Any) -> str | None:
    # Key presence, not truthiness: an API that returns {"error": ""} or
    # {"error": 0} is still reporting an error and must not be rendered as data.
    if isinstance(data, dict) and "error" in data:
        return str(data["error"])
    return None


def format_health(data: dict) -> str:
    err = _is_error(data)
    if err is not None:
        return format_error(f"DCN API error: {err}")
    status = str(data.get("status", "unknown"))
    icon = "✅" if status.lower() in {"ok", "healthy", "up"} else "⚠️"
    devices = data.get("devices_loaded", "?")
    ts = data.get("timestamp", "")
    lines = [f"{icon} *DCN API:* {status}", f"Devices loaded: {devices}"]
    if ts:
        lines.append(f"_{ts}_")
    return truncate("\n".join(lines))


def _as_list(data: Any, *keys: str) -> list:
    """Coerce a payload that is either a bare list or a dict wrapping one."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in keys:
            value = data.get(key)
            if isinstance(value, list):
                return value
    return []


def format_sites(data: Any) -> str:
    err = _is_error(data)
    if err is not None:
        return format_error(err)
    sites = _as_list(data, "sites")
    if not sites:
        return "No sites found."
    rendered = ", ".join(str(s) for s in sites)
    return truncate(f"🗺️ *Sites ({len(sites)}):*\n{rendered}")


def format_devices(data: Any, limit: int = 25) -> str:
    err = _is_error(data)
    if err is not None:
        return format_error(err)
    devices = _as_list(data, "devices")
    if not devices:
        return "No devices found."
    shown = devices[:limit]
    lines = [f"🖥️ *Devices ({len(devices)}):*"]
    for dev in shown:
        if isinstance(dev, dict):
            host = dev.get("hostname") or dev.get("name") or dev.get("ip") or "?"
            site = dev.get("site", "")
            dtype = dev.get("type") or dev.get("vendor") or ""
            meta = " · ".join(p for p in (site, dtype) if p)
            lines.append(f"• `{host}`" + (f" — {meta}" if meta else ""))
        else:
            lines.append(f"• {dev}")
    hidden = len(devices) - len(shown)
    if hidden > 0:
        lines.append(f"…and {hidden} more")
    return truncate("\n".join(lines))


def format_ask(data: Any) -> str:
    """Render the orchestrator (/ask) response, preferring its rendered narrative."""
    err = _is_error(data)
    if err is not None:
        return format_error(err)
    if isinstance(data, dict):
        for key in ("rendered", "output", "answer", "result", "summary"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                agent = data.get("agent")
                header = f"🤖 *{agent}*\n" if agent else ""
                return truncate(header + value.strip())
        return truncate("🤖\n" + json.dumps(data, indent=2, default=str))
    return truncate(str(data))


def format_report(title: str, data: Any) -> str:
    """Generic renderer for endpoints whose schema we don't pin (BGP, topology…).

    Always readable: errors surface plainly, dicts render as key/value lines,
    lists render as a count plus a pretty JSON preview, all length-capped.
    """
    err = _is_error(data)
    if err is not None:
        return format_error(f"{title}: {err}")
    header = f"📊 *{title}*"
    if isinstance(data, dict):
        lines = [header]
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, default=str)
            lines.append(f"• {key}: {value}")
        return truncate("\n".join(lines))
    if isinstance(data, list):
        preview = json.dumps(data, indent=2, default=str)
        return truncate(f"{header} ({len(data)} items)\n```\n{preview}\n```")
    return truncate(f"{header}\n{data}")
