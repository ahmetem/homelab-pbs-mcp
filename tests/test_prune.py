from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from pbs_mcp.tools.prune import (
    PruneDryRunInput,
    PruneInput,
    pbs_prune,
    pbs_prune_dry_run,
)

PRUNE_PATH = "/admin/datastore/teststore/prune"


def test_at_least_one_keep_required():
    with pytest.raises(ValidationError, match="At least one keep-"):
        PruneDryRunInput(backup_type="vm", backup_id="101")


def test_keep_last_zero_is_explicit_and_valid():
    params = PruneDryRunInput(backup_type="vm", backup_id="101", keep_last=0)
    assert params.keep_last == 0


def test_dry_run_separates_keep_and_drop(pbs_config, fake_http, monkeypatch):
    from pbs_mcp import http_client

    async def fake_post(path, params=None, json_body=None):
        fake_http.calls.append(("POST", path, json_body))
        return [
            {"backup-time": 1000, "keep": True, "protected": False},
            {"backup-time": 2000, "keep": False, "protected": False},
            {"backup-time": 3000, "keep": False, "protected": True},
        ]

    monkeypatch.setattr(http_client, "post", fake_post)
    out = asyncio.run(
        pbs_prune_dry_run(
            PruneDryRunInput(backup_type="vm", backup_id="101", keep_daily=7)
        )
    )
    assert "KEEP (1)" in out
    assert "WOULD DROP (2)" in out
    assert "keep-daily=7" in out
    # dry-run flag must actually be sent
    _, path, body = fake_http.calls[0]
    assert path == PRUNE_PATH
    assert body["dry-run"] is True
    assert body["keep-daily"] == 7


def test_prune_reports_dropped(pbs_config_write, fake_http, monkeypatch):
    from pbs_mcp import http_client

    async def fake_post(path, params=None, json_body=None):
        assert "dry-run" not in json_body
        return [
            {"backup-time": 1000, "keep": True, "protected": False},
            {"backup-time": 2000, "keep": False, "protected": False},
        ]

    monkeypatch.setattr(http_client, "post", fake_post)
    out = asyncio.run(
        pbs_prune(
            PruneInput(
                backup_type="vm", backup_id="101", keep_last=1, confirm=True
            )
        )
    )
    assert "Kept 1, dropped 1" in out
    assert "garbage" in out  # points at GC for reclaiming space
