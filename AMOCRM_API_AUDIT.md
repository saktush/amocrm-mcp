# amoCRM MCP server: API audit against official documentation

Date: 2026-10-02. Sources: pages under https://www.amocrm.ru/developers/content/ (leads-api, filters-api, contacts-api, tasks-api, events-and-notes, entity-links-api, unsorted-api, leads_pipelines, tags-api, webhooks-api, custom-fields, oauth/step-by-step, api/recommendations).

Method: every endpoint, parameter and payload in `amocrm_mcp/` was compared with the docs. The doc pages were read through a summarizer, not the raw HTML, and nothing was tested against a live account. Findings are labelled **Confirmed** (the docs contradict the code), **Likely** (the docs imply a problem, but a live call should confirm it) or **Gap** (a capability that is missing).

## 1. Summary

The basic CRUD paths and HTTP methods are correct. The 7 req/s throttle, the single retry on 401, the 429 backoff, and the `_links.next` pagination detection all match the documented behaviour.

The bugs are in query-parameter syntax, token refresh, and what a few tools support:

- Sorting is broken in two tools: `leads_list` and `unsorted_list` send parameter names the API doesn't define.
- `leads_list` filters by `status_id` in a form the API doesn't define.
- `analytics_get_events` accepts a `limit` the API caps lower.
- Token refresh uses a hardcoded domain, a hardcoded `redirect_uri`, and has a race condition with single-use refresh tokens.
- Custom fields can only be addressed by `field_id`, so phone and email fields can't be set by code.
- None of the create or update tools can set tags, a loss reason, or a closing date.

## 2. Defects and fixes

### P1: wrong or likely-rejected requests

| # | Where | Problem | Evidence | Fix |
|---|---|---|---|---|
| 1 | `tools/leads.py:leads_list` | Sends `order[field]=…` and `order[direction]=…`. amoCRM's syntax is `order[created_at]=asc`. The sort is probably ignored or rejected. **Confirmed.** | Docs list `order[updated_at]`, `order[created_at]` and `order[id]`. | Send `params[f"order[{field}]"] = direction`. Restrict `field` to `created_at`, `updated_at` and `id` with a `Literal`. |
| 2 | `tools/unsorted.py:unsorted_list` | Sends `order[by]` and `order[direction]`. **Confirmed.** | Docs allow `created_at` and `updated_at` with `asc` or `desc`. | Same fix as #1. |
| 3 | `tools/leads.py:leads_list` | `status_id` is sent as `filter[status_id][]`. The documented lead status filter is `filter[statuses][0][pipeline_id]` plus `filter[statuses][0][status_id]`, and it needs both IDs. **Confirmed** that the documented form differs; **Likely** that the API ignores or rejects the current one. | filters-api. | Add a `statuses: list[{pipeline_id, status_id}]` input. Build indexed keys. Drop or deprecate the bare `status_id`. |
| 4 | `models/schemas.py:AnalyticsGetEventsInput` | `limit` defaults to 250 and allows 250. Events allow at most 100 per request. **Confirmed.** | events-and-notes. | Override the limit on this model: `le=100`, default 100. |
| 5 | `auth.py:refresh_token` | The URL is hardcoded as `https://{subdomain}.kommo.com/oauth2/access_token`, but API calls go to `{subdomain}.amocrm.ru`. Accounts on the Russian platform likely can't refresh. **Likely.** | oauth/step-by-step says to post to the account's own subdomain, with the domain depending on the platform. The recommendations page says to use account subdomains. | Derive the host from `Config.base_url`, or add an `AMO_BASE_DOMAIN` setting (`amocrm.ru`, `amocrm.com` or `kommo.com`). Use it for both API calls and refresh. |
| 6 | `auth.py:refresh_token` | `redirect_uri` is hardcoded to `https://localhost`. The docs require it to match the integration settings exactly. **Confirmed.** | oauth/step-by-step. | Add an `AMO_REDIRECT_URI` setting. |
| 7 | `client.py:RateLimitedTransport` | Several requests can get a 401 at once, and each calls `refresh_token()`. The refresh token can be exchanged only once. The second call fails with `invalid_grant` and is reported as "Refresh token expired". **Confirmed** (single-use) and **Likely** (race). | oauth/step-by-step. | Add an `asyncio.Lock` around refresh. After acquiring it, compare the current access token with the one that failed and skip the refresh if it already changed. |
| 8 | `models/schemas.py:CustomFieldInput` | It only allows `field_id`. The docs accept `field_id` or `field_code`. System fields like `PHONE` and `EMAIL` are normally addressed by code, and multitext values need `enum_id` or `enum_code`. The input also can't express values like `{"enum_id": …}` safely, because `values` is a free-form dict. **Confirmed** (the model is restrictive). | custom-fields. | Make `field_id` optional and add `field_code`. Require exactly one of them. Document the value shapes per field type in the model description. |
| 9 | `tools/tasks.py:tasks_list` | `is_completed=True` is sent as `filter[is_completed][]=true`. The docs say `1` or `0`. **Likely.** | tasks-api. | Convert to `1` and `0`. |

### P2: smaller correctness and robustness issues

- **`unsorted_accept` sends `pipeline_id`.** The docs only list `user_id` and `status_id` for accept. The extra field is probably ignored; remove it or verify it live. Confirmed that the docs don't define it.
- **`unsorted_reject` can't send `user_id`.** The docs list an optional `user_id` for decline. Add it.
- **`associations_link_entities` restricts `to_entity_type`.** It only allows leads, contacts, companies and customers. The docs also allow `catalog_elements`, with `metadata.catalog_id` and `quantity`. Allow it.
- **Retries on 502 and 504.** The docs say to reduce batch size on 504, but the client doesn't retry gateway errors. Add a small retry for 502, 503 and 504, mainly for idempotent GETs.
- **403 after repeated 429s.** The docs say repeated rate-limit violations lead to HTTP 403 blocking. Surface a clearer message for 403. Add a message for 402, which means the subscription has expired and write requests are blocked. `HTTP_STATUS_MESSAGES` has no 402 entry.
- **Account-wide limit.** The docs state 7 req/s per integration and 50 req/s per account. The limiter is per process. If several instances share an account, they can exceed the per-integration limit together. Note this in the deployment docs.
- **Batch size limits.** The cap is 50 items, which the docs recommend. They allow up to 250, so the cap is a deliberate choice, not an API limit. Make it configurable.
- **Batch responses.** The `batch_*` tool descriptions promise "per-item results including both successes and failures". The code returns whatever the API returns. Check what a partial failure looks like and update the description, or add `request_id` per item so callers can map results back.
- **`leads_create_complex` only sends one lead.** The API takes up to 50 per request, and returns a `merged` flag, `contact_id` and `company_id` when duplicate control merges an entity. Allow a list of leads, and note the `merged` flag in the tool description.
- **`analytics_get_pipeline_analytics`.** It pages through every lead with no upper bound. Add a `max_leads` guard. It also counts closed leads together with open ones and returns no price sums. Add `sum(price)` per group.
- **`normalize_response`.** It flattens `_embedded` into the parent, so an embedded `contacts` or `tags` list becomes a top-level key on the lead. That's fine, but a key that exists on both levels would be silently overwritten. Add a test with a lead that has both.
- **No tests.** The repo has no test suite. The parameter-encoding bugs above (#1 to #4, #9) are the kind that a small `respx`/`httpx.MockTransport` test per tool would catch.

## 3. Gaps in existing tools

- **Tags.** `tags_to_add` and `tags_to_delete` (by `id` or `name`) are supported on create and update for leads, contacts and companies. No tool sets them. `_embedded.tags` is also supported.
- **Lead fields.** Create and update lack `loss_reason_id`, `closed_at`, `created_at`, `updated_at`, `created_by`, `updated_by` and `request_id`. Moving a lead to a lost status without a reason is a common need.
- **Contact and company search.** `contacts_search` and `companies_search` only take `query`. The API also supports `filter`, `order` (contacts: `updated_at` or `id`) and `with` (contacts: `catalog_elements`, `leads`, `customers`). Add the same filters `leads_list` has: `responsible_user_id`, date ranges and custom-field filters.
- **Custom-field filters.** The filter syntax `filter[custom_fields_values][{field_id}][]=…` and the range form are documented. `build_filters` and the list tools don't expose them.
- **Lead `with` values.** `with_related` is a free string. The documented values are `catalog_elements`, `is_price_modified_by_robot`, `loss_reason`, `contacts`, `only_deleted`, `source_id` and `source`. Validate against that list, and add `loss_reason` to the description.
- **`leads_search`** duplicates `leads_list` with `query`. Keep it for discoverability, or fold it in.
- **Tasks.** Missing: `filter[task_type]`, `filter[id]`, `filter[updated_at]`, ordering (`created_at`, `complete_till`, `id`), `duration`, and `result[text]` when completing a task.
- **Notes.** Only `create` and `list` for one entity exist. The docs also have a list across all entities of a type, get by id, update, and pin/unpin. The model only exposes `text` for `common` notes. Other types need a type-specific `params` structure, and the tool descriptions don't say what it is.
- **Associations.** There is no unlink (`POST /{entity}/{id}/unlink`) and no batch link or unlink.
- **Unsorted.** Missing: get by uid, `summary`, `link`, and the `category`, `pipeline_id` and `uid` filters on list.
- **Events.** Missing: get one event, and `GET /api/v4/events/types`, which lists the 35+ valid event type names. The `event_types` filter currently takes strings with no way to discover valid values.
- **Pipelines.** Read-only. Create, edit and delete exist for pipelines and statuses but need admin rights. Fetching a single status is missing. Statuses 142 (won) and 143 (lost) are system statuses; mention them in the tool descriptions.
- **Users.** `account_list_users` has no `with` option and there is no get-one-user tool.

## 4. Suggested new tools

Ordered by likely usefulness. Every area below appears in the official API index.

1. **Tags:** `tags_list`, `tags_create` (`GET` and `POST /api/v4/{entity_type}/tags`). Create returns the existing ID when the name already exists.
2. **Loss reasons:** list loss reasons (`/api/v4/leads/loss_reasons`) so a lead can be closed with a valid `loss_reason_id`. Not fetched from the docs in this audit; confirm the path before building.
3. **Catalogs and products:** list catalogs and catalog elements, since links to `catalog_elements` are already half-supported.
4. **Customers:** customers, customer statuses and segments. The note and link tools already accept `customers`, but there is no way to find one.
5. **Custom field management:** create and update fields, and field groups, for leads, contacts, companies and customers. The list tool already exists.
6. **Webhooks:** list (`GET /api/v4/webhooks`), subscribe (`POST`) and unsubscribe (`DELETE`). Admin rights are required, and the limit is 100 per account.
7. **Sources:** list lead sources, which the leads API can embed and filter on.
8. **Calls API:** log call events against contacts. Useful for telephony integrations.
9. **Talks and chats:** read conversations tied to leads and contacts.
10. **Task types and the account lookup:** expose the task types from `account_get?with=task_types` as a small dedicated tool so an agent can pick `task_type_id` without parsing the whole account object.
11. **Unsorted summary:** a count of accepted and declined unsorted leads and average sort time.
12. **MCP resources and prompts.** Beyond tools, expose pipelines, statuses and custom field definitions as read-only MCP resources. Ship a prompt that explains the lead-creation workflow: find the pipeline, find the status, find the custom field IDs, then create.

## 5. Suggested order of work

1. Fix #1 to #4 and #9: small, local changes with clear docs backing.
2. Fix #5 to #7: token refresh domain, `redirect_uri` and the lock. These can fail on a real account.
3. Rework custom fields (#8) and add tags and loss reason to lead, contact and company create and update.
4. Add filters and ordering to the contact and company search tools, then task and unsorted filters.
5. Add a small test suite with a mocked transport for parameter encoding.
6. Add new tools from section 4, starting with tags, loss reasons and webhooks.

## 6. Limits of this audit

- No live API calls. Anything labelled **Likely** needs a quick check against a real account (a test account is fine).
- The rate-limit page was read in full, but the error-codes page and the individual companies, catalogs, customers and loss-reasons pages were not fetched. Their details above come from the platform index or from general knowledge of the API and should be confirmed before they are built on.
- The amoCRM docs split into amocrm.ru and amocrm.com/kommo.com variants. This audit used the .ru docs, matching `Config.base_url`.
