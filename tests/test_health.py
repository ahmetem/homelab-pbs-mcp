from __future__ import annotations

import asyncio
import time

from pbs_mcp.tools.health import HealthOverviewInput, pbs_health_overview

DS = "teststore"
NOW = time.time()


def _healthy_payloads(fake_http):
    fake_http.get[f"/admin/datastore/{DS}/status"] = {
        "total": 1000 * 1024**3,
        "used": 400 * 1024**3,
        "avail": 600 * 1024**3,
    }
    fake_http.get[f"/admin/datastore/{DS}/gc"] = {
        "upid": "UPID:pbs:1:1:1:garbage_collection::root@pam:",
        "removed-bytes": 10 * 1024**3,
        "pending-bytes": 1024**3,
        "still-bad": 0,
    }
    fake_http.get[f"/admin/datastore/{DS}/groups"] = [
        {
            "backup-type": "vm",
            "backup-id": "101",
            "last-backup": NOW - 3600,
            "files": ["index.json.blob"],
        }
    ]
    fake_http.get[f"/admin/datastore/{DS}/snapshots"] = [
        {"verification": {"state": "ok"}},
        {"verification": {"state": "ok"}},
    ]
    fake_http.get["/nodes/pbs/status"] = {
        "cpu": 0.05,
        "uptime": 400000,
        "memory": {"total": 8 * 1024**3, "used": 2 * 1024**3},
    }
    fake_http.get["/nodes/pbs/tasks"] = []


def test_healthy_overview_says_ok(pbs_config, fake_http):
    _healthy_payloads(fake_http)
    out = asyncio.run(pbs_health_overview(HealthOverviewInput()))
    assert "Verdict: OK" in out
    assert "40.0%" in out  # storage
    assert "2 total; verify: 2 ok" in out
    assert "Failed tasks (last 48h)**: none" in out


def test_unhealthy_overview_lists_issues(pbs_config, fake_http):
    _healthy_payloads(fake_http)
    fake_http.get[f"/admin/datastore/{DS}/status"] = {
        "total": 1000,
        "used": 950,
        "avail": 50,
    }
    fake_http.get[f"/admin/datastore/{DS}/gc"] = {
        "upid": "UPID:pbs:1:1:1:garbage_collection::root@pam:",
        "still-bad": 3,
    }
    fake_http.get[f"/admin/datastore/{DS}/groups"] = [
        {
            "backup-type": "vm",
            "backup-id": "101",
            "last-backup": NOW - 90 * 3600,  # stale
            "files": [],  # corrupt
        }
    ]
    fake_http.get[f"/admin/datastore/{DS}/snapshots"] = [
        {"verification": {"state": "failed"}},
        {"verification": None},
    ]
    fake_http.get["/nodes/pbs/tasks"] = [
        {
            "type": "verify",
            "id": "v-1",
            "starttime": NOW - 600,
            "status": "stopped",
            "exitstatus": "verification failed",
        }
    ]
    out = asyncio.run(pbs_health_overview(HealthOverviewInput()))
    assert "issue(s) found" in out
    assert "95% full" in out
    assert "3 bad chunk(s)" in out
    assert "no manifest" in out
    assert "1 snapshot(s) failed verification" in out
    assert "Newest backup is 90h old" in out
    assert "failed task(s) in the last 48h" in out


def test_partial_api_failure_degrades_gracefully(pbs_config, fake_http):
    import httpx

    _healthy_payloads(fake_http)
    fake_http.get["/nodes/pbs/status"] = httpx.ConnectError("boom")
    out = asyncio.run(pbs_health_overview(HealthOverviewInput()))
    # node section degrades, the rest still renders
    assert "**Node**: status unavailable" in out
    assert "40.0%" in out
