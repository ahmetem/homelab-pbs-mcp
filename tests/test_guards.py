"""Write-guard and config-guard behaviour across all write tools."""
from __future__ import annotations

import asyncio

import pytest

from pbs_mcp import config
from pbs_mcp.tools.gc import RunGcInput, pbs_run_gc
from pbs_mcp.tools.snapshots import (
    ForgetSnapshotInput,
    ProtectSnapshotInput,
    pbs_forget_snapshot,
    pbs_protect_snapshot,
)
from pbs_mcp.tools.tasks import StopTaskInput, pbs_stop_task

UPID = "UPID:pbs:00001234:0000ABCD:00012345:garbage_collection::root@pam!mcp:"


def test_missing_config_reported(monkeypatch):
    monkeypatch.setattr(config, "PBS_HOST", "")
    monkeypatch.setattr(config, "PBS_TOKEN_ID", "")
    monkeypatch.setattr(config, "PBS_TOKEN_SECRET", "x")
    out = asyncio.run(pbs_run_gc(RunGcInput()))
    assert "Missing required env vars" in out
    assert "PBS_HOST" in out and "PBS_TOKEN_ID" in out


@pytest.mark.parametrize(
    "tool,params",
    [
        (pbs_run_gc, RunGcInput(confirm=True)),
        (
            pbs_forget_snapshot,
            ForgetSnapshotInput(
                backup_type="vm",
                backup_id="101",
                backup_time="2026-05-25T10:54:07Z",
                confirm=True,
            ),
        ),
        (
            pbs_protect_snapshot,
            ProtectSnapshotInput(
                backup_type="vm",
                backup_id="101",
                backup_time="2026-05-25T10:54:07Z",
                protected=True,
                confirm=True,
            ),
        ),
        (pbs_stop_task, StopTaskInput(upid=UPID, confirm=True)),
    ],
)
def test_write_disabled_refuses_even_with_confirm(pbs_config, tool, params):
    out = asyncio.run(tool(params))
    assert out.startswith("Refused")
    assert "PBS_ALLOW_WRITE" in out


def test_confirm_required_even_with_write_enabled(pbs_config_write, fake_http):
    out = asyncio.run(pbs_run_gc(RunGcInput(confirm=False)))
    assert out.startswith("Refused")
    assert "confirm=true" in out
    assert fake_http.calls == []  # never reached the API


def test_write_goes_through_with_both_keys(pbs_config_write, fake_http):
    fake_http.post_result = UPID
    out = asyncio.run(pbs_run_gc(RunGcInput(confirm=True, reason="test")))
    assert out.startswith("OK")
    assert UPID in out
    assert fake_http.calls[0][0] == "POST"
