"""Shared fixtures: mocked HTTP only, tmp token file, no repo .env."""

from __future__ import annotations

import json

import httpx
import pytest

from amocrm_mcp import server
from amocrm_mcp.auth import AuthManager
from amocrm_mcp.client import AmoClient
from amocrm_mcp.config import Config


class Recorder:
    """Records outgoing requests and answers from a queue or a handler."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.responses: list[httpx.Response] = []
        self.handler = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.handler is not None:
            return self.handler(request)
        if self.responses:
            return self.responses.pop(0)
        return httpx.Response(200, json={})

    @property
    def last(self) -> httpx.Request:
        return self.requests[-1]

    def last_json(self):
        return json.loads(self.last.content)


@pytest.fixture
def make_config(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # never pick up the repo .env
    for key in list(__import__("os").environ):
        if key.startswith("AMO_"):
            monkeypatch.delenv(key)

    def _make(**overrides) -> Config:
        values = {
            "subdomain": "acme",
            "client_id": "cid",
            "client_secret": "csecret",
            "access_token": "old-access",
            "refresh_token": "old-refresh",
            "token_file": str(tmp_path / "tokens.json"),
        }
        values.update(overrides)
        return Config(_env_file=None, **values)

    return _make


@pytest.fixture
def config(make_config) -> Config:
    return make_config()


@pytest.fixture
def auth(config) -> AuthManager:
    return AuthManager(config)


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
async def amo_client(config, auth, recorder, monkeypatch):
    """AmoClient wired to a mock inner transport and registered as the server global."""
    client = AmoClient(auth=auth, base_url=config.base_url)
    client._transport._inner = httpx.MockTransport(recorder)
    monkeypatch.setattr(server, "_client", client)
    yield client
    await client._client.aclose()


@pytest.fixture
def call_tool(amo_client):
    """Call a registered tool through FastMCP (exercises input validation too)."""
    import amocrm_mcp.tools  # noqa: F401

    async def _call(name: str, /, **input_fields):
        result = await server.mcp.call_tool(name, {"input": input_fields})
        return result.structured_content

    return _call
