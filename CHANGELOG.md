# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
