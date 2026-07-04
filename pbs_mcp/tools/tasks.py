"""Task tracking tools.

PBS runs verify/GC/prune asynchronously and returns a UPID string.
These tools let you check status, tail the log, browse recent tasks,
or abort a stuck task.
"""
from __future__ import annotations

from typing import Any, Optional

import re

from pydantic import BaseModel, ConfigDict, Field

from pbs_mcp import config, http_client
from pbs_mcp.format import fmt_unix_ts, md_table, truncate
from pbs_mcp.mcp_instance import mcp


# UPID format: UPID:node:pid_hex:pstart_hex:starttime_hex:type:id:user@realm[!token]:
_UPID_RE = re.compile(
    r"^UPID:[A-Za-z0-9._-]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:[0-9A-Fa-f]+:"
    r"[A-Za-z0-9_-]+:[^:]*:[A-Za-z0-9._@!-]+:$"
)


def _validate_upid(upid: str) -> Optional[str]:
    if not _UPID_RE.match(upid):
        return (
            f"Error: malformed UPID. Expected "
            f"'UPID:node:...:user@realm:' format, got {upid!r}."
        )
    return None


# ---------- pbs_get_task_status ----------------------------------------------


class GetTaskStatusInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upid: str = Field(
        description=(
            "Full UPID string as returned by run_gc / run_verify / prune. "
            "Format: 'UPID:node:hex:hex:hex:type:id:user@realm:'."
        ),
        max_length=256,
        min_length=10,
    )


@mcp.tool(
    name="pbs_get_task_status",
    annotations={
        "title": "Get PBS task status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_get_task_status(params: GetTaskStatusInput) -> str:
    """Return current state of a PBS task (running / stopped) plus exit
    status if finished."""
    cfg = config.require_config()
    if cfg:
        return cfg
    err = _validate_upid(params.upid)
    if err:
        return err
    try:
        data = await http_client.task_status(params.upid)
    except Exception as exc:
        return http_client.format_http_error(exc)

    if not isinstance(data, dict):
        return f"_Unexpected task status payload: {data!r}_"

    status = data.get("status", "?")
    exitstatus = data.get("exitstatus")
    state_line = f"**{status}**"
    if exitstatus:
        state_line += f"  →  exit: `{exitstatus}`"

    rows = [
        ["Type", data.get("type", "-")],
        ["ID", data.get("id", "-")],
        ["Node", data.get("node", "-")],
        ["User", data.get("user", "-")],
        ["Token", data.get("tokenid", "-") or "-"],
        ["PID", data.get("pid", "-")],
        ["Started", fmt_unix_ts(data.get("starttime"))],
    ]
    return (
        f"## PBS task status\n\n{state_line}\n\n"
        + md_table(["Field", "Value"], rows)
    )


# ---------- pbs_get_task_log -------------------------------------------------


class GetTaskLogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upid: str = Field(max_length=256, min_length=10)
    start: int = Field(
        default=0,
        ge=0,
        description="Line number to start from (0-indexed). Ignored when tail=true.",
    )
    limit: int = Field(
        default=200,
        ge=1,
        le=5000,
        description="Max lines to fetch.",
    )
    tail: bool = Field(
        default=False,
        description=(
            "If true, return the LAST `limit` lines instead of reading from "
            "`start`. Use this to check how a long verify/GC ended."
        ),
    )


def _log_lines(data: Any) -> list[str]:
    if not isinstance(data, list):
        return []
    return [
        f"{entry.get('n', '?'):>5}  {entry.get('t', '')}"
        for entry in data
        if isinstance(entry, dict)
    ]


@mcp.tool(
    name="pbs_get_task_log",
    annotations={
        "title": "Get PBS task log",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_get_task_log(params: GetTaskLogInput) -> str:
    """Fetch log lines from a PBS task. Supports pagination via start/limit,
    or tail=true for just the end of the log — usually all you need to see
    how a verify or GC finished."""
    cfg = config.require_config()
    if cfg:
        return cfg
    err = _validate_upid(params.upid)
    if err:
        return err
    try:
        if params.tail:
            # Probe total line count first, then fetch only the tail window.
            probe = await http_client.task_log(params.upid, start=0, limit=1)
            total = probe.get("total") if isinstance(probe, dict) else None
            if not isinstance(total, int) or total <= 0:
                payload = probe
            else:
                tail_start = max(0, total - params.limit)
                payload = await http_client.task_log(
                    params.upid, start=tail_start, limit=params.limit
                )
        else:
            payload = await http_client.task_log(
                params.upid, start=params.start, limit=params.limit
            )
    except Exception as exc:
        return http_client.format_http_error(exc)

    data = payload.get("data") if isinstance(payload, dict) else payload
    total = payload.get("total") if isinstance(payload, dict) else None
    lines = _log_lines(data)
    if not lines:
        return f"_No log lines for UPID (start={params.start}, limit={params.limit})._"
    header = "## Task log"
    if isinstance(total, int):
        header += f" ({len(lines)} of {total} lines"
        header += ", tail)" if params.tail else ")"
    body = "\n".join(lines)
    return truncate(f"{header}\n\n```\n{body}\n```", limit=8000)


# ---------- pbs_list_tasks ---------------------------------------------------


class ListTasksInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    typefilter: Optional[str] = Field(
        default=None,
        description=(
            "Filter by task type (e.g. 'verify', 'garbage_collection', "
            "'prune', 'backup'). Omit for all types."
        ),
        max_length=64,
        pattern=r"^[a-z_]+$",
    )
    running: Optional[bool] = Field(
        default=None,
        description="If true, only return currently running tasks.",
    )
    limit: int = Field(
        default=20,
        ge=1,
        le=200,
        description="Max tasks to return.",
    )
    errors_only: bool = Field(
        default=False,
        description="If true, only show tasks with a non-OK exitstatus.",
    )


@mcp.tool(
    name="pbs_list_tasks",
    annotations={
        "title": "List recent PBS tasks",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_list_tasks(params: ListTasksInput) -> str:
    """Browse recent PBS tasks with optional type filter, running-only flag,
    and errors-only flag. Running or failed tasks come with their full UPID
    for follow-up via pbs_get_task_status / pbs_get_task_log."""
    cfg = config.require_config()
    if cfg:
        return cfg
    query: dict[str, Any] = {"limit": params.limit}
    if params.typefilter:
        query["typefilter"] = params.typefilter
    if params.running is not None:
        # PBS uses 1/0 for booleans on this endpoint
        query["running"] = 1 if params.running else 0
    if params.errors_only:
        query["errors"] = 1
    try:
        data = await http_client.get(
            f"/nodes/{config.PBS_NODE}/tasks", params=query
        )
    except Exception as exc:
        return http_client.format_http_error(exc)

    if not isinstance(data, list) or not data:
        return "_No tasks match the given filters._"

    rows = []
    followup_upids: list[str] = []
    for t in data:
        status = t.get("status", "?")
        exitstatus = t.get("exitstatus") or ""
        if exitstatus and exitstatus != "OK":
            status_cell = f"{status} ({exitstatus[:30]})"
        else:
            status_cell = status
        upid = t.get("upid") or ""
        # Only running/failed tasks need follow-up; a truncated UPID is
        # useless for that, so hand out the full string for exactly those.
        if upid and (status == "running" or (exitstatus and exitstatus != "OK")):
            followup_upids.append(f"- `{upid}` — {t.get('type', '?')} {status_cell}")
        rows.append(
            [
                t.get("type", "-"),
                t.get("id", "-"),
                fmt_unix_ts(t.get("starttime")),
                status_cell,
                t.get("user", "-"),
            ]
        )
    md = "## Recent PBS tasks\n\n" + md_table(
        ["Type", "ID", "Started (UTC)", "Status", "User"], rows
    )
    if followup_upids:
        shown = followup_upids[:10]
        md += "\n\n**Follow-up UPIDs (running / failed):**\n" + "\n".join(shown)
        if len(followup_upids) > len(shown):
            md += f"\n_... and {len(followup_upids) - len(shown)} more._"
        md += "\n\nUse `pbs_get_task_status` or `pbs_get_task_log` with a full UPID."
    return md


# ---------- pbs_stop_task ------------------------------------------------------


class StopTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    upid: str = Field(
        description="Full UPID of the running task to abort.",
        max_length=256,
        min_length=10,
    )
    confirm: bool = Field(default=False, description="Required.")
    reason: Optional[str] = Field(default=None, max_length=200)


@mcp.tool(
    name="pbs_stop_task",
    annotations={
        "title": "Stop a running PBS task",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_stop_task(params: StopTaskInput) -> str:
    """Abort a running PBS task (e.g. a GC or verify stuck on a slow NFS
    datastore). The task stops at the next safe point; an interrupted GC or
    verify can simply be re-run later. Requires PBS_ALLOW_WRITE=true and
    confirm=true."""
    cfg = config.require_config()
    if cfg:
        return cfg
    block = config.require_write("pbs_stop_task")
    if block:
        return block
    if not params.confirm:
        return (
            "Refused: pbs_stop_task requires confirm=true. "
            "This aborts the running task."
        )
    err = _validate_upid(params.upid)
    if err:
        return err
    try:
        await http_client.stop_task(params.upid)
    except Exception as exc:
        return http_client.format_http_error(exc)

    reason_suffix = f" (reason: {params.reason})" if params.reason else ""
    return (
        f"OK: stop requested for task `{params.upid}`{reason_suffix}. "
        f"Check with `pbs_get_task_status` — the task ends at its next "
        f"abort checkpoint."
    )
