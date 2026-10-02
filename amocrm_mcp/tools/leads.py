"""Lead MCP tools: list, get, create, update, search (FR-9, FR-25, FR-27)."""

from __future__ import annotations

from amocrm_mcp.client import AmoAPIError, build_filters, error_response, success_response
from amocrm_mcp.models.schemas import (
    LeadsCreateInput,
    LeadsGetInput,
    LeadsListInput,
    LeadsSearchInput,
    LeadsUpdateInput,
)
from amocrm_mcp.server import execute_tool, mcp


@mcp.tool()
async def leads_list(input: LeadsListInput) -> dict:
    """List leads with optional filters and pagination.

    Supports filtering by responsible_user_id, statuses (list of
    {pipeline_id, status_id} pairs), pipeline_id, created_at/updated_at/closed_at
    date ranges, and search query. The bare status_id filter is deprecated: it is
    only accepted together with exactly one pipeline_id and is translated into
    statuses pairs. Sorting: order_field (created_at, updated_at, id) with
    order_direction (asc, desc), sent as order[<field>]=<direction>.
    Use with_related to embed contacts, companies, or catalog_elements.
    """

    async def _execute(client):
        params: dict = {"page": input.page, "limit": input.limit}
        if input.with_related:
            params["with"] = input.with_related
        if input.query:
            params["query"] = input.query
        if input.order_field:
            params[f"order[{input.order_field}]"] = input.order_direction or "asc"
        filters = {}
        if input.responsible_user_id:
            filters["responsible_user_id"] = input.responsible_user_id
        statuses = input.effective_statuses()
        for i, st in enumerate(statuses):
            params[f"filter[statuses][{i}][pipeline_id]"] = st.pipeline_id
            params[f"filter[statuses][{i}][status_id]"] = st.status_id
        # Pipeline is already encoded in the statuses pairs when status_id was translated
        if input.pipeline_id and not input.status_id:
            filters["pipeline_id"] = input.pipeline_id
        if input.created_at_from is not None:
            filters["created_at_from"] = input.created_at_from
        if input.created_at_to is not None:
            filters["created_at_to"] = input.created_at_to
        if input.updated_at_from is not None:
            filters["updated_at_from"] = input.updated_at_from
        if input.updated_at_to is not None:
            filters["updated_at_to"] = input.updated_at_to
        if input.closed_at_from is not None:
            filters["closed_at_from"] = input.closed_at_from
        if input.closed_at_to is not None:
            filters["closed_at_to"] = input.closed_at_to
        if filters:
            params.update(build_filters(filters))
        data = await client.request("GET", "/api/v4/leads", params=params)
        leads = data.get("leads", [])
        pagination = {
            "current_page": input.page,
            "has_next": data.get("_has_next", False) if isinstance(data, dict) else False,
        }
        return success_response(leads, pagination)

    return await execute_tool(_execute)


@mcp.tool()
async def leads_get(input: LeadsGetInput) -> dict:
    """Get a single lead by ID.

    Use with_related to embed contacts, companies, or catalog_elements.
    """

    async def _execute(client):
        params = {}
        if input.with_related:
            params["with"] = input.with_related
        data = await client.request(
            "GET", f"/api/v4/leads/{input.id}", params=params or None,
        )
        if not data:
            return error_response("Resource not found", 404, f"No lead with id {input.id} (amoCRM returned 204).")
        return success_response(data)

    return await execute_tool(_execute)


@mcp.tool()
async def leads_create(input: LeadsCreateInput) -> dict:
    """Create a new lead."""

    async def _execute(client):
        payload: dict = {}
        if input.name is not None:
            payload["name"] = input.name
        if input.price is not None:
            payload["price"] = input.price
        if input.status_id is not None:
            payload["status_id"] = input.status_id
        if input.pipeline_id is not None:
            payload["pipeline_id"] = input.pipeline_id
        if input.responsible_user_id is not None:
            payload["responsible_user_id"] = input.responsible_user_id
        if input.custom_fields_values is not None:
            payload["custom_fields_values"] = [
                cf.model_dump(exclude_none=True) for cf in input.custom_fields_values
            ]
        data = await client.request(
            "POST", "/api/v4/leads", json_data=[payload],
        )
        leads = data.get("leads", [data])
        return success_response(leads[0] if len(leads) == 1 else leads)

    return await execute_tool(_execute)


@mcp.tool()
async def leads_update(input: LeadsUpdateInput) -> dict:
    """Update an existing lead by ID."""

    async def _execute(client):
        payload: dict = {"id": input.id}
        if input.name is not None:
            payload["name"] = input.name
        if input.price is not None:
            payload["price"] = input.price
        if input.status_id is not None:
            payload["status_id"] = input.status_id
        if input.pipeline_id is not None:
            payload["pipeline_id"] = input.pipeline_id
        if input.responsible_user_id is not None:
            payload["responsible_user_id"] = input.responsible_user_id
        if input.custom_fields_values is not None:
            payload["custom_fields_values"] = [
                cf.model_dump(exclude_none=True) for cf in input.custom_fields_values
            ]
        data = await client.request(
            "PATCH", "/api/v4/leads", json_data=[payload],
        )
        leads = data.get("leads", [data])
        return success_response(leads[0] if len(leads) == 1 else leads)

    return await execute_tool(_execute)


@mcp.tool()
async def leads_search(input: LeadsSearchInput) -> dict:
    """Search leads by query string with pagination."""

    async def _execute(client):
        params: dict = {
            "query": input.query,
            "page": input.page,
            "limit": input.limit,
        }
        data = await client.request("GET", "/api/v4/leads", params=params)
        leads = data.get("leads", [])
        pagination = {
            "current_page": input.page,
            "has_next": data.get("_has_next", False) if isinstance(data, dict) else False,
        }
        return success_response(leads, pagination)

    return await execute_tool(_execute)
