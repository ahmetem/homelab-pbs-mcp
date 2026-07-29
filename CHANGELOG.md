# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-07-30

### Changed
- **mcp SDK 2.x support** (spec revision 2026-07-28). `pbs_mcp/mcp_instance.py`
  imports `MCPServer` and falls back to `FastMCP` on the 1.x maintenance line;
  it stays the only module that touches the SDK's server class. The decorator
  API did not move, so all 17 tools register unchanged and the 29 tests pass on
  both SDK majors. Verified over real stdio (the exact command Claude Desktop
  runs): `protocol_version=2026-07-28`, 17 tools, `pbs_list_datastores` answering
  from the live PBS.
- **Dependency floor raised to `mcp>=2.0,<3`.** CT 207's autodeploy runs
  `pip install -e .` without `-U`, so any range that mcp 1.29.0 already satisfied
  would have left the deployed venv on the 1.x line forever. Sized as a minor
  release: the server itself still runs on 1.x through the fallback, which is
  also what keeps it alive if that pip step ever fails.
- The previous `<2.0` pin was the 2026-07-29 stop-gap, when an unpinned rebuild
  pulled mcp 2.0.0 and every MCP server on CT 207 failed to start. The cause was
  exactly the `FastMCP` -> `MCPServer` rename this fallback now absorbs.

## [0.3.1] - 2026-07-29

### Fixed
- **Pin `mcp` to `<2.0`.** mcp 2.x removed `mcp.server.fastmcp` (FastMCP moved
  out of the SDK), and this server opens with
  `from mcp.server.fastmcp import FastMCP`. The dependency was declared
  `mcp>=1.2.0` with no upper bound, and homelab-agent's autodeploy refreshes a
  server's venv (`pip install -r` / `-e .`) whenever its manifest changes — so
  on 2026-07-29 a routine rebuild pulled 2.0.0 and **every MCP server on CT 207
  failed to start** with `ModuleNotFoundError`. The agent's whole tool layer was
  dark for ~45 minutes while its dashboard still showed green. No code change is
  needed to run on mcp 1.x; the pin just stops an unattended rebuild from
  crossing the 2.x boundary.

## [0.3.0] - 2026-07-04

### Added
- `pbs_health_overview`: one-call health report — fetches datastore status,
  GC stats, groups, snapshots, node status, and recent tasks concurrently
  and condenses them into a single verdict with flagged issues. Replaces
  five separate tool calls for "is PBS okay?" questions.
- `pbs_list_verify_jobs`: list scheduled verify jobs and their re-verify
  policy (`/config/verify`).
- `pbs_protect_snapshot`: set or clear the protected flag on a snapshot
  (write tool, two-key guarded).
- `pbs_stop_task`: abort a running task, e.g. a GC stuck on a slow NFS
  datastore (write tool, two-key guarded).
- `pbs_list_snapshots`: `limit` parameter (default 50, newest first) and
  `summary=true` mode returning one aggregate row per backup group —
  count, total size, latest snapshot, verify-state breakdown.
- `pbs_get_task_log`: `tail=true` mode fetches only the last `limit` lines,
  the usual need when checking how a long verify/GC ended.
- Test suite (pytest, 29 tests) with a stubbed HTTP layer — covers write
  guards, prune retention validation, snapshot listing/summary, task log
  tail, and the health overview. `pip install -e .[dev]` + `pytest`.

### Changed
- `pbs_list_tasks` no longer prints truncated (unusable) UPIDs in the table;
  instead it hands out **full** UPIDs for exactly the tasks that need
  follow-up (running or failed).
- `pbs_list_snapshots` drops the Owner column (constant in practice, still
  available via `pbs_list_groups`) and caps output instead of dumping every
  snapshot.
- HTTP layer now pools connections in a shared client per event loop and
  retries GET requests once on transient failures (connect error, read
  timeout, and HTTP 403 — the PBS ACL cache lag). Writes never auto-retry.

## [0.2.0] - 2026-05-27

### Changed
- Migrated from a single-file server to the `pbs_mcp` package layout with
  FastMCP + httpx async client; `pbs_mcp.py` kept as a compatibility shim.

## [0.1.0] - 2026-05-27

### Added
- Initial release: 13 tools covering datastore status, snapshot inventory,
  task tracking, garbage collection, verify, and prune over the PBS REST
  API, with a read-only-by-default, two-key write safety model.
