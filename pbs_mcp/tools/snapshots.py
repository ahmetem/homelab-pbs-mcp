"""Backup group / snapshot listing, protection, and deletion tools."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from pbs_mcp import config, http_client
from pbs_mcp.format import fmt_bytes, fmt_unix_ts, md_table
from pbs_mcp.mcp_instance import mcp


# ---------- pbs_list_groups --------------------------------------------------


class ListGroupsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)


@mcp.tool(
    name="pbs_list_groups",
    annotations={
        "title": "List PBS backup groups",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_list_groups(params: ListGroupsInput) -> str:
    """List every backup group on a datastore with its snapshot count,
    last-backup time, owner, and file count. Groups with zero files are
    flagged as likely corrupt."""
    cfg = config.require_config()
    if cfg:
        return cfg
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    try:
        data = await http_client.get(f"/admin/datastore/{ds}/groups")
    except Exception as exc:
        return http_client.format_http_error(exc)

    if not isinstance(data, list) or not data:
        return f"_No backup groups on datastore `{ds}`._"

    rows = []
    corrupt_count = 0
    for grp in data:
        files = grp.get("files") or []
        # A group with an empty `files` array usually means every snapshot is
        # corrupt (missing index.json.blob). Flag that visibly.
        marker = "" if files else " ⚠️"
        if not files:
            corrupt_count += 1
        rows.append(
            [
                f"{grp.get('backup-type', '?')}/{grp.get('backup-id', '?')}{marker}",
                grp.get("backup-count", 0),
                fmt_unix_ts(grp.get("last-backup")),
                grp.get("owner", "-"),
                len(files),
            ]
        )

    md = f"## PBS groups on `{ds}`\n\n" + md_table(
        ["Group", "Snapshots", "Last backup (UTC)", "Owner", "Files"], rows
    )
    if corrupt_count:
        md += (
            f"\n\n⚠️  {corrupt_count} group(s) have no manifest files — "
            f"likely corrupt or interrupted backups. Run `pbs_run_verify` "
            f"to confirm, then `pbs_forget_snapshot` to clean up."
        )
    return md


# ---------- pbs_list_snapshots -----------------------------------------------


class ListSnapshotsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)
    backup_type: Optional[str] = Field(
        default=None,
        description="Filter by 'vm', 'ct', or 'host'.",
        pattern=r"^(vm|ct|host)$",
    )
    backup_id: Optional[str] = Field(
        default=None,
        description="Filter by backup ID (VMID or hostname). Requires backup_type.",
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=1000,
        description="Max snapshots to list, newest first.",
    )
    summary: bool = Field(
        default=False,
        description=(
            "If true, return one aggregate row per backup group (count, "
            "total size, latest snapshot, verify state counts) instead of "
            "one row per snapshot. Much cheaper on large datastores."
        ),
    )


def _snapshot_size(snap: dict) -> int:
    files = snap.get("files") or []
    return snap.get("size") or sum(
        f.get("size") or 0 for f in files if isinstance(f, dict)
    )


def _verify_state(snap: dict) -> Optional[str]:
    verification = snap.get("verification") or {}
    if isinstance(verification, dict):
        return verification.get("state")
    return None


def _summary_table(data: list[dict]) -> str:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for snap in data:
        key = (snap.get("backup-type", "?"), snap.get("backup-id", "?"))
        g = groups.setdefault(
            key,
            {"count": 0, "size": 0, "latest": 0, "ok": 0, "failed": 0, "never": 0},
        )
        g["count"] += 1
        g["size"] += _snapshot_size(snap)
        g["latest"] = max(g["latest"], snap.get("backup-time") or 0)
        state = _verify_state(snap)
        if state == "ok":
            g["ok"] += 1
        elif state is None:
            g["never"] += 1
        else:
            g["failed"] += 1

    rows = []
    for (btype, bid), g in sorted(groups.items()):
        verify_cell = f"{g['ok']} ok"
        if g["failed"]:
            verify_cell += f", {g['failed']} FAILED ❌"
        if g["never"]:
            verify_cell += f", {g['never']} never"
        rows.append(
            [
                f"{btype}/{bid}",
                g["count"],
                fmt_bytes(g["size"]),
                fmt_unix_ts(g["latest"]),
                verify_cell,
            ]
        )
    return md_table(
        ["Group", "Snapshots", "Total size", "Latest (UTC)", "Verify"], rows
    )


@mcp.tool(
    name="pbs_list_snapshots",
    annotations={
        "title": "List PBS snapshots",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_list_snapshots(params: ListSnapshotsInput) -> str:
    """List snapshots on a datastore with size, file count, protected flag,
    and last verify state — newest first, capped at `limit`. Set summary=true
    for one aggregate row per group instead (preferred for overviews)."""
    cfg = config.require_config()
    if cfg:
        return cfg
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    query: dict[str, Any] = {}
    if params.backup_type:
        query["backup-type"] = params.backup_type
    if params.backup_id:
        if not params.backup_type:
            return "Error: backup_id requires backup_type."
        query["backup-id"] = params.backup_id
    try:
        data = await http_client.get(
            f"/admin/datastore/{ds}/snapshots", params=query or None
        )
    except Exception as exc:
        return http_client.format_http_error(exc)

    if not isinstance(data, list) or not data:
        scope = (
            f"`{params.backup_type}/{params.backup_id}`"
            if params.backup_id
            else f"type `{params.backup_type}`" if params.backup_type else "any"
        )
        return f"_No snapshots on `{ds}` matching {scope}._"

    if params.summary:
        return (
            f"## PBS snapshot summary on `{ds}` "
            f"({len(data)} snapshots)\n\n" + _summary_table(data)
        )

    data.sort(key=lambda s: s.get("backup-time") or 0, reverse=True)
    total_count = len(data)
    shown = data[: params.limit]

    rows = []
    for snap in shown:
        protected = "yes" if snap.get("protected") else "no"
        rows.append(
            [
                snap.get("backup-type", "?"),
                snap.get("backup-id", "?"),
                fmt_unix_ts(snap.get("backup-time")),
                fmt_bytes(_snapshot_size(snap)),
                len(snap.get("files") or []),
                protected,
                _verify_state(snap) or "-",
            ]
        )

    md = f"## PBS snapshots on `{ds}`\n\n" + md_table(
        ["Type", "ID", "Time (UTC)", "Size", "Files", "Protected", "Verify"],
        rows,
    )
    if total_count > len(shown):
        md += (
            f"\n\n_Showing newest {len(shown)} of {total_count}. Raise `limit`, "
            f"filter by backup_type/backup_id, or use summary=true._"
        )
    return md


# ---------- pbs_protect_snapshot ----------------------------------------------


class ProtectSnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)
    backup_type: str = Field(
        description="'vm', 'ct', or 'host'.", pattern=r"^(vm|ct|host)$"
    )
    backup_id: str = Field(
        description="VMID or hostname.",
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    backup_time: str = Field(
        description=(
            "Snapshot timestamp in PBS ISO format, e.g. '2026-05-25T10:54:07Z'. "
            "Get from pbs_list_snapshots (the 'Time' column gives this format)."
        ),
        max_length=40,
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
    )
    protected: bool = Field(
        description="true to protect the snapshot, false to remove protection."
    )
    confirm: bool = Field(default=False, description="Required.")
    reason: Optional[str] = Field(default=None, max_length=200)


@mcp.tool(
    name="pbs_protect_snapshot",
    annotations={
        "title": "Set PBS snapshot protection",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def pbs_protect_snapshot(params: ProtectSnapshotInput) -> str:
    """Set or clear the protected flag on one snapshot. Protected snapshots
    are skipped by prune and cannot be forgotten until unprotected.
    Requires PBS_ALLOW_WRITE=true and confirm=true."""
    cfg = config.require_config()
    if cfg:
        return cfg
    block = config.require_write("pbs_protect_snapshot")
    if block:
        return block
    if not params.confirm:
        return (
            "Refused: pbs_protect_snapshot requires confirm=true. "
            "This changes whether prune/forget can touch the snapshot."
        )
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    try:
        await http_client.put(
            f"/admin/datastore/{ds}/protected",
            params={
                "backup-type": params.backup_type,
                "backup-id": params.backup_id,
                "backup-time": params.backup_time,
            },
            json_body={"protected": params.protected},
        )
    except Exception as exc:
        return http_client.format_http_error(exc)

    state = "PROTECTED" if params.protected else "unprotected"
    reason_suffix = f" (reason: {params.reason})" if params.reason else ""
    return (
        f"OK: snapshot `{params.backup_type}/{params.backup_id}/"
        f"{params.backup_time}` on `{ds}` is now {state}{reason_suffix}."
    )


# ---------- pbs_forget_snapshot ----------------------------------------------


class ForgetSnapshotInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    datastore: Optional[str] = Field(default=None, max_length=64)
    backup_type: str = Field(
        description="'vm', 'ct', or 'host'.", pattern=r"^(vm|ct|host)$"
    )
    backup_id: str = Field(
        description="VMID or hostname.",
        max_length=64,
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    backup_time: str = Field(
        description=(
            "Snapshot timestamp in PBS ISO format, e.g. '2026-05-25T10:54:07Z'. "
            "Get from pbs_list_snapshots (the 'Time' column gives this format)."
        ),
        max_length=40,
        pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$",
    )
    confirm: bool = Field(default=False, description="Required.")
    reason: Optional[str] = Field(default=None, max_length=200)


@mcp.tool(
    name="pbs_forget_snapshot",
    annotations={
        "title": "Delete a PBS snapshot",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def pbs_forget_snapshot(params: ForgetSnapshotInput) -> str:
    """Permanently delete one snapshot. The on-disk chunks are freed by the
    next garbage collection. Requires PBS_ALLOW_WRITE=true and confirm=true."""
    cfg = config.require_config()
    if cfg:
        return cfg
    block = config.require_write("pbs_forget_snapshot")
    if block:
        return block
    if not params.confirm:
        return (
            "Refused: pbs_forget_snapshot requires confirm=true. "
            "This deletes the snapshot permanently."
        )
    try:
        ds = config.resolve_datastore(params.datastore)
    except config.PbsConfigError as e:
        return f"Error: {e}"
    try:
        await http_client.delete(
            f"/admin/datastore/{ds}/snapshots",
            params={
                "backup-type": params.backup_type,
                "backup-id": params.backup_id,
                "backup-time": params.backup_time,
            },
        )
    except Exception as exc:
        return http_client.format_http_error(exc)

    reason_suffix = f" (reason: {params.reason})" if params.reason else ""
    return (
        f"OK: snapshot `{params.backup_type}/{params.backup_id}/"
        f"{params.backup_time}` removed from `{ds}`{reason_suffix}. "
        f"Chunks freed by next garbage collection."
    )
