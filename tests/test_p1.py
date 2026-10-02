"""P1 fixes: exact outgoing query strings / bodies / refresh behaviour."""

from __future__ import annotations

import asyncio
import json
from urllib.parse import parse_qsl

import httpx
import pytest
from pydantic import ValidationError

from amocrm_mcp.auth import AuthManager, RefreshTokenExpiredError
from amocrm_mcp.client import AmoClient
from amocrm_mcp.models.schemas import (
    AnalyticsGetEventsInput,
    CustomFieldInput,
    LeadsCreateInput,
    LeadsListInput,
    UnsortedListInput,
)


def query(request: httpx.Request) -> list[tuple[str, str]]:
    return parse_qsl(request.url.query.decode(), keep_blank_values=True)


# ---- #1 / #2 order params ----------------------------------------------------


async def test_leads_list_order(call_tool, recorder):
    await call_tool("leads_list", order_field="updated_at", order_direction="desc", limit=10)
    q = query(recorder.last)
    assert ("order[updated_at]", "desc") in q
    assert not any(k in ("order[field]", "order[direction]") for k, _ in q)


async def test_leads_list_order_default_direction_asc(call_tool, recorder):
    await call_tool("leads_list", order_field="id")
    assert ("order[id]", "asc") in query(recorder.last)


def test_leads_list_order_field_restricted():
    with pytest.raises(ValidationError):
        LeadsListInput(order_field="name")


async def test_unsorted_list_order(call_tool, recorder):
    await call_tool("unsorted_list", order_by="created_at", order_direction="asc")
    q = query(recorder.last)
    assert ("order[created_at]", "asc") in q
    assert not any(k.startswith("order[by") or k == "order[direction]" for k, _ in q)
    assert recorder.last.url.path == "/api/v4/leads/unsorted"


def test_order_direction_requires_field():
    with pytest.raises(ValidationError, match="order_field"):
        LeadsListInput(order_direction="desc")
    with pytest.raises(ValidationError, match="order_by"):
        UnsortedListInput(order_direction="desc")


def test_unsorted_order_field_restricted():
    with pytest.raises(ValidationError):
        UnsortedListInput(order_by="id")


# ---- #3 statuses filter ------------------------------------------------------


async def test_leads_list_statuses(call_tool, recorder):
    await call_tool(
        "leads_list",
        statuses=[{"pipeline_id": 1, "status_id": 10}, {"pipeline_id": 2, "status_id": 20}],
    )
    q = dict(query(recorder.last))
    assert q["filter[statuses][0][pipeline_id]"] == "1"
    assert q["filter[statuses][0][status_id]"] == "10"
    assert q["filter[statuses][1][pipeline_id]"] == "2"
    assert q["filter[statuses][1][status_id]"] == "20"


async def test_leads_list_status_id_with_pipeline_translated(call_tool, recorder):
    await call_tool("leads_list", status_id=[10, 11], pipeline_id=[5])
    q = query(recorder.last)
    d = dict(q)
    assert d["filter[statuses][0][pipeline_id]"] == "5"
    assert d["filter[statuses][0][status_id]"] == "10"
    assert d["filter[statuses][1][pipeline_id]"] == "5"
    assert d["filter[statuses][1][status_id]"] == "11"
    assert not any(k.startswith("filter[status_id]") for k, _ in q)


def test_leads_list_status_id_without_pipeline_rejected():
    with pytest.raises(ValidationError, match="pipeline_id"):
        LeadsListInput(status_id=[10])


def test_leads_list_status_id_with_many_pipelines_rejected():
    with pytest.raises(ValidationError, match="exactly one pipeline_id"):
        LeadsListInput(status_id=[10], pipeline_id=[1, 2])


async def test_leads_list_pipeline_only_filter_unchanged(call_tool, recorder):
    await call_tool("leads_list", pipeline_id=[5])
    assert ("filter[pipeline_id][]", "5") in query(recorder.last)


# ---- #4 events limit ---------------------------------------------------------


def test_events_limit_default_and_cap():
    assert AnalyticsGetEventsInput().limit == 100
    with pytest.raises(ValidationError):
        AnalyticsGetEventsInput(limit=101)
    assert AnalyticsGetEventsInput(limit=100).limit == 100


async def test_events_request_limit(call_tool, recorder):
    await call_tool("analytics_get_events")
    assert ("limit", "100") in query(recorder.last)


# ---- #5 / #6 base domain + redirect uri --------------------------------------


def test_config_defaults(config):
    assert config.base_url == "https://acme.amocrm.ru"
    assert config.token_url == "https://acme.amocrm.ru/oauth2/access_token"
    assert config.redirect_uri == "https://localhost"


async def test_refresh_uses_configured_domain_and_redirect(make_config, respx_mock):
    cfg = make_config(base_domain="kommo.com", redirect_uri="https://example.org/cb")
    assert cfg.base_url == "https://acme.kommo.com"
    route = respx_mock.post("https://acme.kommo.com/oauth2/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "new-a", "refresh_token": "new-r"})
    )
    auth = AuthManager(cfg)
    await auth.refresh_token()
    body = json.loads(route.calls.last.request.content)
    assert body["redirect_uri"] == "https://example.org/cb"
    assert body["grant_type"] == "refresh_token"
    assert body["refresh_token"] == "old-refresh"
    assert auth.get_access_token() == "new-a"
    saved = json.loads(open(cfg.token_file).read())
    assert saved == {"access_token": "new-a", "refresh_token": "new-r"}


async def test_refresh_invalid_grant(auth, respx_mock):
    respx_mock.post("https://acme.amocrm.ru/oauth2/access_token").mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"})
    )
    with pytest.raises(RefreshTokenExpiredError):
        await auth.refresh_token()


# ---- #7 refresh lock ---------------------------------------------------------


async def test_concurrent_401s_refresh_once(config, auth, respx_mock):
    refresh_route = respx_mock.post("https://acme.amocrm.ru/oauth2/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "new-a", "refresh_token": "new-r"})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.headers["Authorization"] == "Bearer new-a":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(401, json={"title": "Unauthorized"})

    client = AmoClient(auth=auth, base_url=config.base_url)
    client._transport._inner = httpx.MockTransport(handler)
    try:
        results = await asyncio.gather(
            *(client.request("GET", "/api/v4/leads") for _ in range(4))
        )
    finally:
        await client._client.aclose()
    assert refresh_route.call_count == 1
    assert all(r["ok"] is True for r in results)


async def test_refresh_skipped_when_token_changed(auth, respx_mock):
    route = respx_mock.post("https://acme.amocrm.ru/oauth2/access_token")
    await auth.refresh_token(stale_token="something-else")
    assert route.call_count == 0


# ---- #8 custom fields --------------------------------------------------------


def test_custom_field_requires_exactly_one_identifier():
    CustomFieldInput(field_id=1, values=[{"value": "x"}])
    CustomFieldInput(field_code="PHONE", values=[{"value": "+1"}])
    with pytest.raises(ValidationError):
        CustomFieldInput(values=[{"value": "x"}])
    with pytest.raises(ValidationError):
        CustomFieldInput(field_id=1, field_code="PHONE", values=[{"value": "x"}])


async def test_custom_field_dump_excludes_none(call_tool, recorder):
    recorder.responses.append(httpx.Response(200, json={"_embedded": {"leads": [{"id": 1}]}}))
    await call_tool(
        "leads_create",
        name="L",
        custom_fields_values=[
            {"field_code": "PHONE", "values": [{"value": "+1", "enum_code": "WORK"}]},
            {"field_id": 7, "values": [{"value": "x"}]},
        ],
    )
    assert recorder.last_json() == [
        {
            "name": "L",
            "custom_fields_values": [
                {"field_code": "PHONE", "values": [{"value": "+1", "enum_code": "WORK"}]},
                {"field_id": 7, "values": [{"value": "x"}]},
            ],
        }
    ]


def test_leads_create_input_accepts_code_fields():
    LeadsCreateInput(custom_fields_values=[{"field_code": "EMAIL", "values": [{"value": "a@b.c"}]}])


# ---- #9 is_completed ---------------------------------------------------------


@pytest.mark.parametrize("flag,expected", [(True, "1"), (False, "0")])
async def test_tasks_list_is_completed(call_tool, recorder, flag, expected):
    await call_tool("tasks_list", is_completed=flag)
    q = query(recorder.last)
    assert ("filter[is_completed]", expected) in q
    assert ("filter[is_completed][]", expected) not in q


# ---- registration ------------------------------------------------------------


async def test_all_36_tools_register():
    import amocrm_mcp.tools  # noqa: F401
    from amocrm_mcp import server

    tools = await server.mcp.list_tools()
    assert len(tools) == server.EXPECTED_TOOL_COUNT == 36
