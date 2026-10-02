"""P2 robustness items."""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import ValidationError

from amocrm_mcp import client as client_module
from amocrm_mcp.client import HTTP_STATUS_MESSAGES, normalize_response
from amocrm_mcp.models.schemas import (
    AssociationsLinkEntitiesInput,
    UnsortedAcceptInput,
    resolve_max_batch_size,
)
from tests.test_p1 import query


@pytest.fixture(autouse=True)
def sleeps(monkeypatch):
    """Record backoff delays instead of sleeping."""
    delays: list[float] = []

    async def _fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(client_module, "_sleep", _fake_sleep)
    return delays


# ---- unsorted accept / reject ------------------------------------------------


async def test_unsorted_accept_does_not_send_pipeline_id(call_tool, recorder):
    await call_tool("unsorted_accept", uid="abc", user_id=3, status_id=9, pipeline_id=2)
    req = recorder.last
    assert req.method == "POST"
    assert req.url.path == "/api/v4/leads/unsorted/abc/accept"
    assert recorder.last_json() == {"user_id": 3, "status_id": 9}
    assert "pipeline_id" not in UnsortedAcceptInput.model_fields


async def test_unsorted_reject_without_user_has_no_body(call_tool, recorder):
    await call_tool("unsorted_reject", uid="abc")
    req = recorder.last
    assert req.method == "DELETE"
    assert req.url.path == "/api/v4/leads/unsorted/abc/decline"
    assert req.content == b""


async def test_unsorted_reject_with_user_sends_json_body(call_tool, recorder):
    await call_tool("unsorted_reject", uid="abc", user_id=5)
    assert recorder.last.method == "DELETE"
    assert recorder.last_json() == {"user_id": 5}


# ---- associations ------------------------------------------------------------


async def test_link_catalog_elements(call_tool, recorder):
    recorder.responses.append(httpx.Response(200, json={"_embedded": {"links": [{"ok": 1}]}}))
    await call_tool(
        "associations_link_entities",
        entity_type="leads",
        entity_id=1,
        to_entity_type="catalog_elements",
        to_entity_id=77,
        metadata={"catalog_id": 12, "quantity": 2},
    )
    assert recorder.last.url.path == "/api/v4/leads/1/link"
    assert recorder.last_json() == [
        {
            "to_entity_id": 77,
            "to_entity_type": "catalog_elements",
            "metadata": {"catalog_id": 12, "quantity": 2},
        }
    ]


def test_catalog_elements_not_allowed_as_source():
    with pytest.raises(ValidationError):
        AssociationsLinkEntitiesInput(
            entity_type="catalog_elements", entity_id=1, to_entity_type="leads", to_entity_id=2
        )


# ---- gateway retries ---------------------------------------------------------


@pytest.mark.parametrize("status", [502, 503, 504])
async def test_get_retried_on_gateway_errors(amo_client, recorder, sleeps, status):
    recorder.responses.extend(
        [httpx.Response(status), httpx.Response(status), httpx.Response(200, json={"ok": True})]
    )
    data = await amo_client.request("GET", "/api/v4/leads")
    assert data["ok"] is True
    assert len(recorder.requests) == 3
    assert sleeps == [0.5, 1.0]


async def test_get_retry_is_bounded(amo_client, recorder, sleeps):
    recorder.handler = lambda r: httpx.Response(504, json={"detail": "timeout"})
    with pytest.raises(client_module.AmoAPIError) as exc:
        await amo_client.request("GET", "/api/v4/leads")
    assert exc.value.status_code == 504
    assert len(recorder.requests) == 4
    assert sleeps == [0.5, 1.0, 2.0]


async def test_gateway_retry_then_401_refreshes_once(amo_client, recorder, respx_mock):
    refresh = respx_mock.post("https://acme.amocrm.ru/oauth2/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "new-a", "refresh_token": "new-r"})
    )

    def handler(request):
        if request.headers["Authorization"] == "Bearer new-a":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(502) if len(recorder.requests) == 1 else httpx.Response(401)

    recorder.handler = handler
    data = await amo_client.request("GET", "/api/v4/leads")
    assert data["ok"] is True
    assert refresh.call_count == 1


async def test_gateway_retry_then_429_backs_off(amo_client, recorder, sleeps):
    recorder.responses.extend(
        [httpx.Response(504), httpx.Response(429, headers={"Retry-After": "3"}), httpx.Response(200, json={"ok": True})]
    )
    data = await amo_client.request("GET", "/api/v4/leads")
    assert data["ok"] is True
    assert sleeps == [0.5, 3.0]


async def test_post_not_retried_on_gateway_error(amo_client, recorder):
    recorder.handler = lambda r: httpx.Response(502, json={})
    with pytest.raises(client_module.AmoAPIError):
        await amo_client.request("POST", "/api/v4/leads", json_data=[{"name": "x"}])
    assert len(recorder.requests) == 1


def test_status_messages_402_403():
    assert "subscription" in HTTP_STATUS_MESSAGES[402]
    assert "429" in HTTP_STATUS_MESSAGES[403]
    assert 503 in HTTP_STATUS_MESSAGES


# ---- batch size --------------------------------------------------------------


def test_max_batch_size_env():
    assert resolve_max_batch_size({}) == 50
    assert resolve_max_batch_size({"AMO_MAX_BATCH_SIZE": "100"}) == 100
    assert resolve_max_batch_size({"AMO_MAX_BATCH_SIZE": "9999"}) == 250
    assert resolve_max_batch_size({"AMO_MAX_BATCH_SIZE": "0"}) == 1
    assert resolve_max_batch_size({"AMO_MAX_BATCH_SIZE": "abc"}) == 50


async def test_batch_default_cap_enforced(monkeypatch):
    from amocrm_mcp.models import schemas
    from amocrm_mcp.models.schemas import BatchCreateLeadsInput

    monkeypatch.delenv("AMO_MAX_BATCH_SIZE", raising=False)
    monkeypatch.setattr(schemas, "MAX_BATCH_SIZE", schemas.resolve_max_batch_size())
    BatchCreateLeadsInput(items=[{"name": "x"}] * 50)
    with pytest.raises(ValidationError):
        BatchCreateLeadsInput(items=[{"name": "x"}] * 51)


# ---- pipeline analytics ------------------------------------------------------


def _lead(i, status, user, price):
    return {"id": i, "status_id": status, "responsible_user_id": user, "price": price}


async def test_pipeline_analytics_sums_price(call_tool, recorder):
    recorder.responses.append(
        httpx.Response(
            200,
            json={
                "_embedded": {
                    "leads": [_lead(1, 10, 1, 100), _lead(2, 10, 1, 50), _lead(3, 11, 2, 0)]
                }
            },
        )
    )
    result = await call_tool("analytics_get_pipeline_analytics", pipeline_id=4)
    assert ("filter[pipeline_id][]", "4") in query(recorder.last)
    assert result["data"] == [
        {"status_id": 10, "responsible_user_id": 1, "count": 2, "sum_price": 150},
        {"status_id": 11, "responsible_user_id": 2, "count": 1, "sum_price": 0},
    ]
    assert result["pagination"]["truncated"] is False
    assert result["pagination"]["total_leads"] == 3


async def test_pipeline_analytics_max_leads_guard(call_tool, recorder):
    page = {
        "_links": {"next": {"href": "x"}},
        "_embedded": {"leads": [_lead(i, 10, 1, 10) for i in range(5)]},
    }
    recorder.handler = lambda r: httpx.Response(200, json=page)
    result = await call_tool("analytics_get_pipeline_analytics", pipeline_id=4, max_leads=8)
    assert len(recorder.requests) == 2  # stopped despite more pages
    assert result["pagination"]["total_leads"] == 8
    assert result["pagination"]["truncated"] is True
    assert result["data"] == [
        {"status_id": 10, "responsible_user_id": 1, "count": 8, "sum_price": 80}
    ]


# ---- leads_create_complex ----------------------------------------------------


async def test_create_complex_surfaces_merge_fields(call_tool, recorder):
    recorder.responses.append(
        httpx.Response(
            200,
            json=[{"id": 1, "contact_id": 2, "company_id": 3, "merged": True, "request_id": "0"}],
        )
    )
    result = await call_tool(
        "leads_create_complex",
        name="L",
        contacts=[{"name": "C", "custom_fields_values": [{"field_code": "PHONE", "values": [{"value": "1"}]}]}],
    )
    assert recorder.last.url.path == "/api/v4/leads/complex"
    assert recorder.last_json() == [
        {
            "name": "L",
            "_embedded": {
                "contacts": [
                    {
                        "name": "C",
                        "custom_fields_values": [
                            {"field_code": "PHONE", "values": [{"value": "1"}]}
                        ],
                    }
                ]
            },
        }
    ]
    assert result["data"] == {
        "id": 1, "contact_id": 2, "company_id": 3, "merged": True, "request_id": "0",
    }


# ---- normalize_response (documents current behaviour) -----------------------


def test_normalize_embedded_key_overwrites_top_level_key():
    """Current behaviour: an _embedded key wins over a same-named top-level key."""
    data = {
        "id": 1,
        "tags": "top-level",
        "_links": {"self": {"href": "x"}},
        "_embedded": {"tags": [{"id": 5, "_links": {}}], "contacts": [{"id": 9}]},
    }
    assert normalize_response(data) == {
        "id": 1,
        "tags": [{"id": 5}],
        "contacts": [{"id": 9}],
    }


def test_batch_cap_configurable_at_runtime(monkeypatch):
    from amocrm_mcp.models import schemas

    monkeypatch.setattr(schemas, "MAX_BATCH_SIZE", 50)
    schemas.configure_max_batch_size(10)
    with pytest.raises(ValidationError):
        schemas.BatchCreateLeadsInput(items=[{}] * 11)
    schemas.configure_max_batch_size(9999)
    assert schemas.MAX_BATCH_SIZE == 250


def test_env_example_loads_via_config(tmp_path, monkeypatch):
    """Every key in .env.example must be accepted by Config (extras are forbidden)."""
    from pathlib import Path

    from amocrm_mcp.config import Config

    example = Path(__file__).resolve().parent.parent / ".env.example"
    env_file = tmp_path / ".env"
    env_file.write_text(example.read_text())
    monkeypatch.chdir(tmp_path)
    for key in list(__import__("os").environ):
        if key.startswith("AMO_"):
            monkeypatch.delenv(key)
    cfg = Config(_env_file=str(env_file))
    assert cfg.max_batch_size == 50
    assert cfg.base_domain == "amocrm.ru"
    env_file.write_text(example.read_text().replace("AMO_MAX_BATCH_SIZE=50", "AMO_MAX_BATCH_SIZE=999"))
    assert Config(_env_file=str(env_file)).max_batch_size == 250


@pytest.mark.parametrize("tool,args", [
    ("leads_get", {"id": 1}), ("contacts_get", {"id": 1}), ("companies_get", {"id": 1}),
    ("tasks_get", {"id": 1}), ("pipelines_get", {"pipeline_id": 1}),
])
async def test_get_by_id_204_is_not_found(tool, args, call_tool, recorder):
    recorder.responses.append(httpx.Response(204))
    r = await call_tool(tool, **args)
    assert r["status_code"] == 404 and r["error"] == "Resource not found"
