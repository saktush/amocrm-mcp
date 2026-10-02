"""amocrm-mcp-auth: code exchange, callback parsing, CLI wiring (mocked HTTP)."""

import json

import httpx
import pytest

from amocrm_mcp import auth_setup
from amocrm_mcp.auth import AuthError, AuthManager


async def test_exchange_code_persists_tokens(make_config, respx_mock):
    cfg = make_config(access_token="", refresh_token="", redirect_uri="http://localhost:8765/cb")
    route = respx_mock.post("https://acme.amocrm.ru/oauth2/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "A", "refresh_token": "R"})
    )
    await AuthManager(cfg).exchange_code("the-code")
    body = json.loads(route.calls.last.request.content)
    assert body["grant_type"] == "authorization_code" and body["code"] == "the-code"
    assert body["redirect_uri"] == "http://localhost:8765/cb"
    assert json.loads(open(cfg.token_file).read()) == {"access_token": "A", "refresh_token": "R"}


async def test_exchange_code_error(make_config, respx_mock):
    cfg = make_config()
    respx_mock.post("https://acme.amocrm.ru/oauth2/access_token").mock(return_value=httpx.Response(400, json={"hint": "bad"}))
    with pytest.raises(AuthError):
        await AuthManager(cfg).exchange_code("x")


def test_parse_callback():
    assert auth_setup.parse_callback("/?code=abc&state=s1&referer=x", "s1") == "abc"
    with pytest.raises(AuthError):
        auth_setup.parse_callback("/?code=abc&state=other", "s1")
    with pytest.raises(AuthError):
        auth_setup.parse_callback("/?state=s1", "s1")


def test_authorize_url(make_config):
    url = auth_setup.authorize_url(make_config(), "st")
    assert url.startswith("https://www.amocrm.ru/oauth?") and "client_id=cid" in url and "state=st" in url


def test_wait_for_code_rejects_non_local_redirect():
    with pytest.raises(AuthError):
        auth_setup.wait_for_code("https://example.com/cb", "s", 8765)


def test_cli_with_code_never_prints_tokens(tmp_path, monkeypatch, respx_mock, capsys):
    monkeypatch.chdir(tmp_path)
    for k in list(__import__("os").environ):
        if k.startswith("AMO_"):
            monkeypatch.delenv(k)
    env = tmp_path / "t.env"
    env.write_text(f"AMO_SUBDOMAIN=acme\nAMO_CLIENT_ID=cid\nAMO_CLIENT_SECRET=sec\nAMO_TOKEN_FILE={tmp_path}/tok.json\n")
    respx_mock.post("https://acme.amocrm.ru/oauth2/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "tokA-9f3", "refresh_token": "tokR-9f3"})
    )
    assert auth_setup.main(["--env-file", str(env), "--code", "c"]) == 0
    out = capsys.readouterr()
    assert "9f3" not in out.out + out.err
    assert json.loads((tmp_path / "tok.json").read_text())["refresh_token"] == "tokR-9f3"


def test_cli_requires_client_credentials(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    for k in list(__import__("os").environ):
        if k.startswith("AMO_"):
            monkeypatch.delenv(k)
    env = tmp_path / "t.env"
    env.write_text("AMO_SUBDOMAIN=acme\n")
    assert auth_setup.main(["--env-file", str(env)]) == 2
