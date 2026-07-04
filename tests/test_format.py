from __future__ import annotations

from pbs_mcp.format import fmt_bytes, fmt_unix_ts, md_table, truncate


def test_fmt_bytes():
    assert fmt_bytes(None) == "-"
    assert fmt_bytes(0) == "0 B"
    assert fmt_bytes(512) == "512 B"
    assert fmt_bytes(1536) == "1.5 KB"
    assert fmt_bytes(3 * 1024**3) == "3.0 GB"


def test_fmt_unix_ts():
    assert fmt_unix_ts(None) == "-"
    assert fmt_unix_ts(0) == "-"
    assert fmt_unix_ts(1748170447) == "2025-05-25T10:54:07Z"


def test_md_table():
    out = md_table(["A", "B"], [[1, None], ["x", "y"]])
    lines = out.splitlines()
    assert lines[0] == "| A | B |"
    assert lines[1] == "| --- | --- |"
    assert lines[2] == "| 1 |  |"
    assert lines[3] == "| x | y |"


def test_truncate():
    assert truncate("short") == "short"
    long = "a" * 5000
    out = truncate(long, limit=100)
    assert out.startswith("a" * 100)
    assert "truncated, total 5000 chars" in out
