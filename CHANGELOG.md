# Changelog

## Unreleased (branch `fix/api-audit-p1-p2`)

Fixes from the API audit (`AMOCRM_API_AUDIT.md`), verified against a live dev account.

### Fixed
- `leads_list` / `unsorted_list` sorting now sends `order[<field>]=asc|desc` (was `order[field]`/`order[by]`).
- `leads_list` status filter uses `filter[statuses][i][pipeline_id|status_id]`; new `statuses` input.
- `analytics_get_events` `limit` capped at 100 (default 100).
- `tasks_list` `is_completed` sent as scalar `filter[is_completed]=1|0` (the bracket form with `0` returned completed tasks).
- `leads_get`, `contacts_get`, `companies_get`, `tasks_get`, `pipelines_get` return a 404 error for a missing id instead of an empty success.
- Custom fields accept `field_code` (e.g. `PHONE`, `EMAIL`) as well as `field_id`.
- Token refresh: host and `redirect_uri` are configurable (`AMO_BASE_DOMAIN`, `AMO_REDIRECT_URI`); concurrent 401s refresh once.
- `unsorted_accept` no longer sends `pipeline_id`; `unsorted_reject` accepts `user_id`; `associations_link_entities` allows `catalog_elements` as target.
- GET requests retry on 502/503/504; clearer 402/403 messages.
- `AMO_MAX_BATCH_SIZE` (default 50, max 250); `analytics_get_pipeline_analytics` gains `max_leads` and `sum_price`; `leads_create_complex` returns `merged`, `contact_id`, `company_id`.

### Added
- `amocrm-mcp-auth`: one-time OAuth bootstrap (authorization code or local browser callback) that writes the first token pair to `AMO_TOKEN_FILE`.
- Long-lived token mode: without a refresh token a 401 is reported clearly and never refreshed. Startup logs the token source and mode, and warns when `AMO_ACCESS_TOKEN` is shadowed by a token file.
- Test suite (`tests/`, mocked HTTP): `pip install -e '.[dev]' && pytest`.

### Changed (upgrade notes)
- **Token refresh host defaults to `amocrm.ru`** (it was hardcoded to `kommo.com`). Kommo accounts must set `AMO_BASE_DOMAIN=kommo.com`.
- **`leads_list`: `status_id` now requires exactly one `pipeline_id`** (or use `statuses`); `order_direction` requires `order_field`.
- `AMO_ACCESS_TOKEN` is optional when a token file exists. Use one token file per account/environment (`.amo_tokens*.json` is gitignored).
