from __future__ import annotations

import asyncio

from pbs_mcp.tools.snapshots import (
    ListGroupsInput,
    ListSnapshotsInput,
    ProtectSnapshotInput,
    pbs_list_groups,
    pbs_list_snapshots,
    pbs_protect_snapshot,
)

SNAP_PATH = "/admin/datastore/teststore/snapshots"
GROUPS_PATH = "/admin/datastore/teststore/groups"


def _snap(bid: str, t: int, state=None, size=1024, protected=False):
    verification = {"state": state} if state else None
    return {
        "backup-type": "vm",
        "backup-id": bid,
        "backup-time": t,
        "size": size,
        "files": [{"filename": "index.json.blob", "size": size}],
        "verification": verification,
        "protected": protected,
        "owner": "root@pam!mcp",
    }


def test_list_snapshots_sorted_and_limited(pbs_config, fake_http):
    fake_http.get[SNAP_PATH] = [_snap("101", 1000 + i) for i in range(10)]
    out = asyncio.run(pbs_list_snapshots(ListSnapshotsInput(limit=3)))
    assert "Showing newest 3 of 10" in out
    # newest first: 1009 shows up, 1000 doesn't
    assert "1970-01-01T00:16:49Z" in out  # ts 1009
    assert "1970-01-01T00:16:40Z" not in out  # ts 1000


def test_list_snapshots_no_truncation_note_when_all_shown(pbs_config, fake_http):
    fake_http.get[SNAP_PATH] = [_snap("101", 1000)]
    out = asyncio.run(pbs_list_snapshots(ListSnapshotsInput()))
    assert "Showing newest" not in out


def test_list_snapshots_summary_aggregates(pbs_config, fake_http):
    fake_http.get[SNAP_PATH] = [
        _snap("101", 1000, state="ok"),
        _snap("101", 2000, state="failed"),
        _snap("101", 3000),
        _snap("205", 5000, state="ok", size=2048),
    ]
    out = asyncio.run(pbs_list_snapshots(ListSnapshotsInput(summary=True)))
    assert "4 snapshots" in out
    assert "vm/101" in out and "vm/205" in out
    assert "1 ok, 1 FAILED ❌, 1 never" in out
    assert "2.0 KB" in out  # vm/205 total size


def test_list_snapshots_backup_id_requires_type(pbs_config, fake_http):
    out = asyncio.run(pbs_list_snapshots(ListSnapshotsInput(backup_id="101")))
    assert "backup_id requires backup_type" in out


def test_list_groups_flags_corrupt(pbs_config, fake_http):
    fake_http.get[GROUPS_PATH] = [
        {
            "backup-type": "vm",
            "backup-id": "101",
            "backup-count": 5,
            "last-backup": 1000,
            "owner": "root@pam!mcp",
            "files": ["index.json.blob"],
        },
        {
            "backup-type": "ct",
            "backup-id": "205",
            "backup-count": 2,
            "last-backup": 2000,
            "owner": "root@pam!mcp",
            "files": [],
        },
    ]
    out = asyncio.run(pbs_list_groups(ListGroupsInput()))
    assert "ct/205 ⚠️" in out
    assert "1 group(s) have no manifest files" in out


def test_protect_snapshot_sends_put(pbs_config_write, fake_http):
    out = asyncio.run(
        pbs_protect_snapshot(
            ProtectSnapshotInput(
                backup_type="vm",
                backup_id="101",
                backup_time="2026-05-25T10:54:07Z",
                protected=True,
                confirm=True,
            )
        )
    )
    assert out.startswith("OK")
    assert "PROTECTED" in out
    verb, path, payload = fake_http.calls[0]
    assert verb == "PUT"
    assert path == "/admin/datastore/teststore/protected"
    assert payload["json"] == {"protected": True}
    assert payload["params"]["backup-id"] == "101"
