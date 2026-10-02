# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Python (>=3.11) MCP server for amoCRM/Kommo API v4, built on FastMCP 3.x. Exposes 36 tools. Tests live in `tests/` (mocked HTTP only); no linter is configured.

## Commands

```bash
pip install -e .                      # install (a .venv exists in the repo root)
python -m amocrm_mcp                  # run, stdio transport (default)
AMO_TRANSPORT=http AMO_PORT=8000 python -m amocrm_mcp   # Streamable HTTP at /mcp (sse is also supported, at /sse)
pip install -e '.[dev]'               # test deps (pytest, pytest-asyncio, respx)
.venv/bin/python -m pytest -q         # run all tests (no network, no real .env)
.venv/bin/python -m pytest tests/test_p1.py::test_leads_list_order -q   # single test
amocrm-mcp-auth --code <code>        # one-time OAuth bootstrap: writes tokens to AMO_TOKEN_FILE (see README)
docker compose up --build             # containerized HTTP deployment (see README-deploy.md)
```

Config is read from env vars prefixed `AMO_` (and a `.env` in the CWD) via `amocrm_mcp/config.py`. `AMO_SUBDOMAIN` and `AMO_ACCESS_TOKEN` are required; `.env.example` lists the rest. `AMO_TOKEN_FILE` (default `.amo_tokens.json`) is where tokens are persisted; it overrides env tokens, so use a separate file per account/environment (e.g. `.amo_tokens.dev.json` for `dev.env`). First tokens come from `amocrm-mcp-auth`; refresh tokens are single-use and rotated on every refresh.

## Architecture

Startup flow (`amocrm_mcp/server.py`): `Config` → `AuthManager` → `AmoClient` stored in the module-global `_client` → `import amocrm_mcp.tools` (side-effect import; each `@mcp.tool()` decorator registers on the module-level `mcp` FastMCP instance) → assert tool count == `EXPECTED_TOOL_COUNT` → run transport.

Things that span files:

- **Tool-count guard.** `server.py` exits with an error if the registered tool count differs from `EXPECTED_TOOL_COUNT` (36). When adding or removing a tool, update that constant, the per-module comments in `tools/__init__.py`, and the counts in `pyproject.toml`/README.
- **Tool pattern.** Each module in `amocrm_mcp/tools/` defines `@mcp.tool()` async functions taking one Pydantic input model from `models/schemas.py`. The body defines an inner `async def _execute(client)` that calls `client.request(...)` and returns `success_response(...)`; it is dispatched via `await execute_tool(_execute)`. `execute_tool` injects the global client and converts `AmoAPIError`/`AuthError` into error envelopes. New tools must be imported in `tools/__init__.py` to register.
- **Response envelopes** (`client.py`): success is `{data, pagination?}`; errors are `{error, status_code, detail}`. Tools return error dicts rather than raising.
- **HTTP client** (`client.py`): `AmoClient` wraps an `httpx.AsyncClient` using `RateLimitedTransport`, which injects the bearer token, throttles to 7 req/s (aiolimiter), refreshes the token and retries once on 401, and does exponential backoff on 429. Responses are passed through `normalize_response`, which strips `_links` and flattens `_embedded`; `_has_next` is derived from `_links.next` before stripping and consumed by tools for pagination.
- **Filters.** `build_filters` converts flat keys to amoCRM bracket syntax (`foo_from`/`foo_to` → `filter[foo][from|to]`, other values → `filter[key][]`).
- **Auth** (`auth.py`): the token file on disk takes precedence over env tokens (env is only the seed). Refreshes write atomically (temp file + `os.replace`). Refresh is serialized by an `asyncio.Lock` (refresh tokens are single-use) and skipped if another request already rotated the token. The API host and the refresh URL both derive from `AMO_BASE_DOMAIN` (default `amocrm.ru`; set `kommo.com` for Kommo accounts), and `AMO_REDIRECT_URI` must match the integration settings.
- **Input validation** (`models/schemas.py`): limits such as batch size (default 50, configurable via `AMO_MAX_BATCH_SIZE`, max 250), page limit max 250, and 40 custom fields per entity are enforced by Pydantic before any network call.

`AMOCRM_API_AUDIT.md` records the audit of the tools against the official amoCRM API docs. Its P1/P2 defects were fixed on `fix/api-audit-p1-p2`; the remaining items (section 3 gaps, section 4 new tools) are still open. Check it before changing query-building code.

Source comments cite internal requirement IDs (FR-n, ADR-n, C-n) that are not defined in this repo.
