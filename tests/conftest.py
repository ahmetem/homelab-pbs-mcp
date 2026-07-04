"""Shared fixtures: fake config and a dispatching fake HTTP layer.

Tests monkeypatch the http_client module functions, so no real network
and no httpx plumbing — tool logic (guards, formatting, aggregation) is
what's under test.
"""
from __future__ import annotations

import pytest

from pbs_mcp import config


@pytest.fixture
def pbs_config(monkeypatch):
    """Complete read-only config with a default datastore."""
    monkeypatch.setattr(config, "PBS_HOST", "https://pbs.test:8007")
    monkeypatch.setattr(config, "PBS_TOKEN_ID", "root@pam!test")
    monkeypatch.setattr(config, "PBS_TOKEN_SECRET", "s3cret")
    monkeypatch.setattr(config, "PBS_NODE", "pbs")
    monkeypatch.setattr(config, "PBS_DEFAULT_DATASTORE", "teststore")
    monkeypatch.setattr(config, "PBS_ALLOW_WRITE", False)


@pytest.fixture
def pbs_config_write(pbs_config, monkeypatch):
    """Same as pbs_config but with writes enabled."""
    monkeypatch.setattr(config, "PBS_ALLOW_WRITE", True)


@pytest.fixture
def fake_http(monkeypatch):
    """Patch http_client verbs with a path-keyed dispatcher.

    Usage:
        fake_http.get["/admin/datastore/teststore/status"] = {...}
    Records every call in fake_http.calls as (verb, path, params/body).
    """
    from pbs_mcp import http_client

    class Fake:
        def __init__(self):
            self.get = {}
            self.calls = []
            self.post_result = None
            self.put_result = None
            self.delete_result = None

    fake = Fake()

    async def fake_get(path, params=None):
        fake.calls.append(("GET", path, params))
        result = fake.get[path]
        if isinstance(result, Exception):
            raise result
        return result

    async def fake_get_full(path, params=None):
        fake.calls.append(("GET_FULL", path, params))
        result = fake.get[path]
        if isinstance(result, Exception):
            raise result
        return result

    async def fake_post(path, params=None, json_body=None):
        fake.calls.append(("POST", path, {"params": params, "json": json_body}))
        return fake.post_result

    async def fake_put(path, params=None, json_body=None):
        fake.calls.append(("PUT", path, {"params": params, "json": json_body}))
        return fake.put_result

    async def fake_delete(path, params=None):
        fake.calls.append(("DELETE", path, params))
        return fake.delete_result

    monkeypatch.setattr(http_client, "get", fake_get)
    monkeypatch.setattr(http_client, "get_full", fake_get_full)
    monkeypatch.setattr(http_client, "post", fake_post)
    monkeypatch.setattr(http_client, "put", fake_put)
    monkeypatch.setattr(http_client, "delete", fake_delete)
    return fake
