"""Aggregate health overview: one call, one compact report.

Answers "is anything broken?" without walking through five separate
tools. Fetches datastore status, GC stats, groups, snapshots, node
status, and recent tasks concurrently, then condenses everything into
a short verdict + bullet list.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from pbs_mcp import config, http_client
from pbs_mcp.format import fmt_bytes, fmt_unix_ts
from pbs_mcp.mcp_instance import mcp


class HealthOverviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)
    task_hours: int = Field(
        default=48,
        ge=1,
        le=720,
        description="Look-back window for failed tasks, in hours.",
    )
    stale_hours: int = Field(
        default=36,
        ge=1,
        le=8760,
        description=(
            "Flag the datastore if the newest backup is older than this "
            "many hours."
        ),
    )


def _fmt_uptime(seconds: Any) -> str:
    try:
        s = int(seconds)
    except (TypeError, ValueError):
        return "-"
    days, rem = divmod(s, 86400)
    hours = rem // 3600
    return f"{days}d {hours}h" if days else f"{hours}h"


@mcp.tool(
    name="pbs_health_overview",
    annotations={
        "title": "PBS health overview",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_health_overview(params: HealthOverviewInput) -> str:
    """One-call health report for a datastore: storage usage, node load,
    last GC result, snapshot/verify coverage, backup freshness, corrupt
    groups, and failed/running tasks. Start here for any 'is PBS okay?'
    question — it replaces separate status/gc/tasks/groups calls."""
    cfg = config.require_config()
    if cfg:
        return cfg
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"

    node = config.PBS_NODE
    results = await asyncio.gather(
        http_client.get(f"/admin/datastore/{ds}/status"),
        http_client.get(f"/admin/datastore/{ds}/gc"),
        http_client.get(f"/admin/datastore/{ds}/groups"),
        http_client.get(f"/admin/datastore/{ds}/snapshots"),
        http_client.get(f"/nodes/{node}/status"),
        http_client.get(f"/nodes/{node}/tasks", params={"errors": 1, "limit": 50}),
        http_client.get(f"/nodes/{node}/tasks", params={"running": 1, "limit": 20}),
        return_exceptions=True,
    )
    status, gc, groups, snapshots, node_status, error_tasks, running_tasks = results

    now = time.time()
    issues: list[str] = []
    lines: list[str] = []

    # --- storage -------------------------------------------------------------
    if isinstance(status, dict):
        total = status.get("total", 0) or 0
        used = status.get("used", 0) or 0
        avail = status.get("avail", 0) or 0
        pct = (used / total * 100.0) if total else 0.0
        lines.append(
            f"- **Storage**: {fmt_bytes(used)} / {fmt_bytes(total)} used "
            f"({pct:.1f}%), {fmt_bytes(avail)} free"
        )
        if pct >= 90:
            issues.append(f"❌ Datastore {pct:.0f}% full — prune/GC needed soon")
        elif pct >= 80:
            issues.append(f"⚠️ Datastore {pct:.0f}% full")
    else:
        lines.append(f"- **Storage**: unavailable ({http_client.format_http_error(status)})")

    # --- node ------------------------------------------------------------------
    if isinstance(node_status, dict):
        cpu = node_status.get("cpu")
        mem = node_status.get("memory") or {}
        mem_total = mem.get("total") or 0
        mem_used = mem.get("used") or 0
        mem_pct = (mem_used / mem_total * 100.0) if mem_total else 0.0
        cpu_str = f"{cpu * 100:.0f}%" if isinstance(cpu, (int, float)) else "-"
        lines.append(
            f"- **Node**: uptime {_fmt_uptime(node_status.get('uptime'))}, "
            f"CPU {cpu_str}, RAM {mem_pct:.0f}% of {fmt_bytes(mem_total)}"
        )
        if mem_pct >= 90:
            issues.append(f"⚠️ Node RAM at {mem_pct:.0f}%")
    else:
        lines.append("- **Node**: status unavailable")

    # --- last GC ----------------------------------------------------------------
    if isinstance(gc, dict):
        if not gc.get("upid"):
            lines.append("- **Last GC**: never run")
            issues.append("⚠️ GC has never run on this datastore")
        else:
            pending = gc.get("pending-bytes")
            removed = gc.get("removed-bytes")
            still_bad = gc.get("still-bad", 0) or 0
            gc_line = (
                f"- **Last GC**: removed {fmt_bytes(removed)}, "
                f"pending {fmt_bytes(pending)}"
            )
            if still_bad:
                gc_line += f", still-bad chunks: {still_bad}"
                issues.append(f"❌ GC reports {still_bad} bad chunk(s) on disk")
            lines.append(gc_line)
    else:
        lines.append("- **Last GC**: unavailable")

    # --- groups / freshness -------------------------------------------------------
    if isinstance(groups, list):
        corrupt = [g for g in groups if not (g.get("files") or [])]
        newest = max(
            (g.get("last-backup") or 0 for g in groups), default=0
        )
        lines.append(
            f"- **Groups**: {len(groups)}, newest backup "
            f"{fmt_unix_ts(newest) if newest else 'none'}"
        )
        if corrupt:
            names = ", ".join(
                f"{g.get('backup-type', '?')}/{g.get('backup-id', '?')}"
                for g in corrupt[:5]
            )
            issues.append(
                f"❌ {len(corrupt)} group(s) with no manifest (likely corrupt): {names}"
            )
        if newest and (now - newest) > params.stale_hours * 3600:
            age_h = (now - newest) / 3600
            issues.append(
                f"⚠️ Newest backup is {age_h:.0f}h old (threshold {params.stale_hours}h)"
            )
        if not groups:
            issues.append("⚠️ Datastore has no backup groups at all")
    else:
        lines.append("- **Groups**: unavailable")

    # --- snapshot verify coverage --------------------------------------------------
    if isinstance(snapshots, list):
        ok = failed = never = 0
        for snap in snapshots:
            verification = snap.get("verification") or {}
            state = (
                verification.get("state")
                if isinstance(verification, dict)
                else None
            )
            if state == "ok":
                ok += 1
            elif state is None:
                never += 1
            else:
                failed += 1
        verify_line = f"- **Snapshots**: {len(snapshots)} total; verify: {ok} ok"
        if failed:
            verify_line += f", {failed} FAILED"
            issues.append(f"❌ {failed} snapshot(s) failed verification")
        if never:
            verify_line += f", {never} never verified"
        lines.append(verify_line)
    else:
        lines.append("- **Snapshots**: unavailable")

    # --- tasks -------------------------------------------------------------------
    cutoff = now - params.task_hours * 3600
    if isinstance(error_tasks, list):
        recent_failed = [
            t for t in error_tasks if (t.get("starttime") or 0) >= cutoff
        ]
        if recent_failed:
            summaries = "; ".join(
                f"{t.get('type', '?')} {t.get('id') or ''} "
                f"({(t.get('exitstatus') or '?')[:40]})".strip()
                for t in recent_failed[:5]
            )
            lines.append(
                f"- **Failed tasks (last {params.task_hours}h)**: "
                f"{len(recent_failed)} — {summaries}"
            )
            issues.append(
                f"⚠️ {len(recent_failed)} failed task(s) in the last "
                f"{params.task_hours}h — see pbs_list_tasks errors_only=true"
            )
        else:
            lines.append(f"- **Failed tasks (last {params.task_hours}h)**: none")
    else:
        lines.append("- **Failed tasks**: unavailable")

    if isinstance(running_tasks, list) and running_tasks:
        running_str = ", ".join(
            f"{t.get('type', '?')} (since {fmt_unix_ts(t.get('starttime'))})"
            for t in running_tasks[:5]
        )
        lines.append(f"- **Running tasks**: {len(running_tasks)} — {running_str}")
    else:
        lines.append("- **Running tasks**: none")

    if issues:
        verdict = f"**Verdict: {len(issues)} issue(s) found**\n" + "\n".join(
            issues
        )
    else:
        verdict = "**Verdict: OK** — no issues detected"

    return f"## PBS health — datastore `{ds}`\n\n{verdict}\n\n" + "\n".join(lines)
