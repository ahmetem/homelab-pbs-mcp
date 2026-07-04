"""Async HTTP helpers for the Proxmox Backup Server REST API.

Built on httpx.AsyncClient — no blocking I/O on the asyncio loop.

Connections are pooled in a shared client (one per event loop) so
multi-request tools like pbs_health_overview don't pay a TLS handshake
per call. GET requests retry once on transient failures: connect errors,
read timeouts, and HTTP 403 (PBS caches ACLs for a few seconds after a
grant, so a fresh token can 403 spuriously).
"""
from __future__ import annotations

import asyncio
import urllib.parse
from typing import Any, Optional

import httpx

from pbs_mcp import config

# Delay before the single GET retry. 403 retries wait longer because the
# PBS ACL cache takes ~3s to pick up new grants.
RETRY_DELAY_TRANSIENT = 1.0
RETRY_DELAY_ACL = 2.5

# One client per event loop: FastMCP runs a single loop in production, but
# tests may spin up a fresh loop per test case.
_clients: dict[int, httpx.AsyncClient] = {}


def _client() -> httpx.AsyncClient:
    """Return the shared AsyncClient for the running event loop, creating
    it on first use."""
    loop_key = id(asyncio.get_running_loop())
    client = _clients.get(loop_key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            base_url=config.base_url(),
            headers=config.auth_header(),
            verify=config.PBS_VERIFY_TLS,
            timeout=config.PBS_HTTP_TIMEOUT,
        )
        _clients[loop_key] = client
    return client


def format_http_error(exc: Exception) -> str:
    """Translate httpx exceptions into the markdown error strings tools
    return to the LLM."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        body = exc.response.text[:500]
        if status == 401:
            return (
                "Error: PBS authentication failed (HTTP 401). "
                "Check PBS_TOKEN_ID and PBS_TOKEN_SECRET."
            )
        if status == 403:
            return (
                f"Error: PBS permission denied (HTTP 403). "
                f"Token lacks the required privilege.\n\n{body}"
            )
        if status == 404:
            return f"Error: PBS resource not found (HTTP 404).\n\n{body}"
        return f"Error: PBS HTTP {status}.\n\n{body}"
    if isinstance(exc, httpx.ConnectError):
        return f"Error: cannot connect to {config.PBS_HOST}: {exc}"
    if isinstance(exc, httpx.TimeoutException):
        return f"Error: PBS request timed out after {config.PBS_HTTP_TIMEOUT}s"
    return f"Error: {type(exc).__name__}: {exc}"


def _unwrap(payload: Any) -> Any:
    """PBS wraps every response in {'data': ...}. Tools want the inner value."""
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


async def _get_response(path: str, params: Optional[dict]) -> httpx.Response:
    """GET with a single retry on transient failures. Safe because GET is
    idempotent; POST/DELETE/PUT never auto-retry."""
    c = _client()
    try:
        r = await c.get(path, params=params)
    except (httpx.ConnectError, httpx.ReadTimeout):
        await asyncio.sleep(RETRY_DELAY_TRANSIENT)
        r = await c.get(path, params=params)
    if r.status_code == 403:
        await asyncio.sleep(RETRY_DELAY_ACL)
        r = await c.get(path, params=params)
    r.raise_for_status()
    return r


async def get(path: str, params: Optional[dict] = None) -> Any:
    r = await _get_response(path, params)
    return _unwrap(r.json())


async def get_full(path: str, params: Optional[dict] = None) -> Any:
    """Like get(), but return the whole JSON payload without unwrapping —
    some endpoints (task log) carry metadata like 'total' next to 'data'."""
    r = await _get_response(path, params)
    return r.json()


async def post(
    path: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> Any:
    c = _client()
    r = await c.post(path, params=params, json=json_body)
    r.raise_for_status()
    return _unwrap(r.json())


async def put(
    path: str,
    params: Optional[dict] = None,
    json_body: Optional[dict] = None,
) -> Any:
    c = _client()
    r = await c.put(path, params=params, json=json_body)
    r.raise_for_status()
    return _unwrap(r.json())


async def delete(path: str, params: Optional[dict] = None) -> Any:
    c = _client()
    r = await c.delete(path, params=params)
    r.raise_for_status()
    return _unwrap(r.json())


# ----- task helpers ---------------------------------------------------------


def encode_upid(upid: str) -> str:
    """PBS task endpoints want the UPID URL-encoded (colons → %3A)."""
    return urllib.parse.quote(upid, safe="")


async def task_status(upid: str) -> Any:
    encoded = encode_upid(upid)
    return await get(f"/nodes/{config.PBS_NODE}/tasks/{encoded}/status")


async def task_log(
    upid: str,
    *,
    start: int | None = None,
    limit: int | None = None,
) -> Any:
    """Return the full task-log payload: {'data': [...], 'total': N}."""
    encoded = encode_upid(upid)
    params: dict[str, Any] = {}
    if start is not None:
        params["start"] = start
    if limit is not None:
        params["limit"] = limit
    return await get_full(
        f"/nodes/{config.PBS_NODE}/tasks/{encoded}/log",
        params=params or None,
    )


async def stop_task(upid: str) -> Any:
    encoded = encode_upid(upid)
    return await delete(f"/nodes/{config.PBS_NODE}/tasks/{encoded}")
