from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from pbs_mcp import http_client
from pbs_mcp.tools.tasks import (
    GetTaskLogInput,
    GetTaskStatusInput,
    ListTasksInput,
    pbs_get_task_log,
    pbs_get_task_status,
    pbs_list_tasks,
)

UPID = "UPID:pbs:00001234:0000ABCD:00012345:verify::root@pam!mcp:"
TASKS_PATH = "/nodes/pbs/tasks"


def test_malformed_upid_rejected(pbs_config):
    out = asyncio.run(
        pbs_get_task_status(GetTaskStatusInput(upid="not-a-upid-at-all"))
    )
    assert "malformed UPID" in out


def test_list_tasks_full_upid_only_for_followup(pbs_config, fake_http):
    fake_http.get[TASKS_PATH] = [
        {
            "type": "verify",
            "id": "v-1",
            "starttime": 1000,
            "status": "stopped",
            "exitstatus": "OK",
            "user": "root@pam",
            "upid": UPID.replace("verify", "verify_ok"),
        },
        {
            "type": "garbage_collection",
            "id": "gc-1",
            "starttime": 2000,
            "status": "running",
            "exitstatus": None,
            "user": "root@pam",
            "upid": UPID.replace("verify", "gc_running"),
        },
        {
            "type": "prune",
            "id": "p-1",
            "starttime": 3000,
            "status": "stopped",
            "exitstatus": "ERROR: it broke",
            "user": "root@pam",
            "upid": UPID.replace("verify", "prune_failed"),
        },
    ]
    out = asyncio.run(pbs_list_tasks(ListTasksInput()))
    # OK task: no UPID anywhere
    assert "verify_ok" not in out
    # running and failed tasks: full UPID present, uncut
    assert UPID.replace("verify", "gc_running") in out
    assert UPID.replace("verify", "prune_failed") in out
    assert "Follow-up UPIDs" in out
    assert "..." not in out.split("Follow-up UPIDs")[1].split("Use `pbs_")[0]


def test_task_log_tail_fetches_last_lines(pbs_config, fake_http, monkeypatch):
    total = 500
    calls = []

    async def fake_task_log(upid, *, start=None, limit=None):
        calls.append((start, limit))
        lines = [
            {"n": i + 1, "t": f"line {i + 1}"}
            for i in range(start, min(start + limit, total))
        ]
        return {"data": lines, "total": total}

    monkeypatch.setattr(http_client, "task_log", fake_task_log)
    out = asyncio.run(pbs_get_task_log(GetTaskLogInput(upid=UPID, tail=True, limit=50)))
    # probe first, then the tail window
    assert calls == [(0, 1), (450, 50)]
    assert "line 500" in out
    assert "line 449" not in out
    assert "(50 of 500 lines, tail)" in out


def test_task_log_plain_pagination(pbs_config, fake_http, monkeypatch):
    async def fake_task_log(upid, *, start=None, limit=None):
        return {
            "data": [{"n": start + 1, "t": "hello"}],
            "total": 10,
        }

    monkeypatch.setattr(http_client, "task_log", fake_task_log)
    out = asyncio.run(pbs_get_task_log(GetTaskLogInput(upid=UPID, start=4, limit=1)))
    assert "hello" in out
    assert "(1 of 10 lines)" in out


def test_task_log_limit_validation():
    with pytest.raises(ValidationError):
        GetTaskLogInput(upid=UPID, limit=0)
    with pytest.raises(ValidationError):
        GetTaskLogInput(upid=UPID, limit=999999)
