# amoCRM MCP Server

MCP server for [amoCRM](https://www.amocrm.ru/) (Kommo) API v4. Exposes 36 tools for leads, contacts, companies, tasks, notes, pipelines, associations, analytics, and more.

Built with [FastMCP](https://github.com/jlowin/fastmcp). Works with Claude Desktop, Cursor, and any MCP-compatible client.

## Features

- **36 MCP tools** across 11 domains (leads, contacts, companies, tasks, notes, pipelines, associations, account, batch, unsorted, analytics)
- **OAuth 2.0** token refresh with disk persistence
- **Rate limiting** — 7 req/s with automatic 429 backoff and jitter
- **HAL+JSON normalization** — strips `_links`, flattens `_embedded`
- **Consistent response envelopes** — `{data, pagination}` or `{error, status_code, detail}`
- **stdio and SSE** transports

## Quick Start

### 1. Install

```bash
pip install -e .
```

### 2. Configure

Copy `.env.example` to `.env` and fill in your amoCRM credentials:

```bash
cp .env.example .env
```

You need at minimum:
- `AMO_SUBDOMAIN` — your amoCRM account subdomain
- `AMO_ACCESS_TOKEN` — OAuth access token

For automatic token refresh, also set:
- `AMO_CLIENT_ID`, `AMO_CLIENT_SECRET`, `AMO_REFRESH_TOKEN`

### 3. Run

**On your local machine**, from the repo root with the venv active:

```bash
# stdio (default — used by the desktop/CLI clients below)
python -m amocrm_mcp
```

**On a server** (headless, accessed remotely), use the Streamable HTTP transport instead of stdio:

```bash
AMO_TRANSPORT=http AMO_PORT=8000 python -m amocrm_mcp
```

Then point any MCP client that supports Streamable HTTP at `http://<server-host>:8000/mcp`. Run it under a process supervisor (systemd, `tmux`, `supervisord`, etc.) so it survives disconnects. A legacy `AMO_TRANSPORT=sse` mode is also available (`http://<server-host>:8000/sse`) for older clients, but Streamable HTTP is the modern standard and the only transport OpenAI Codex supports remotely — prefer `http` unless a specific client requires SSE.

For a network-reachable deployment via Docker (any Linux server or Docker Desktop) — including step-by-step instructions for connecting Claude, Codex, and Cursor to a remote server — see [README-deploy.md](README-deploy.md).

> **Important:** every client below spawns the server as a subprocess with its own restricted `PATH` — it will **not** find a bare `python` on `$PATH` the way your shell does. Always give clients the **absolute path** to this project's venv interpreter, e.g. `/absolute/path/to/amocrm-mcp/.venv/bin/python`. Using a bare `"python"` command is the most common cause of a client reporting `Failed to spawn process: No such file or directory`.

## Connect to a Client

All snippets assume you've already done steps 1–2 above. Replace `/absolute/path/to/amocrm-mcp` with this repo's actual path, and fill in your real `AMO_SUBDOMAIN`/`AMO_ACCESS_TOKEN` (or rely on the `.env` file the server reads automatically, in which case the `env` blocks below can be omitted for local use).

### Claude Desktop

Edit `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "amocrm": {
      "command": "/absolute/path/to/amocrm-mcp/.venv/bin/python",
      "args": ["-m", "amocrm_mcp"],
      "env": {
        "AMO_SUBDOMAIN": "your-subdomain",
        "AMO_ACCESS_TOKEN": "your-token"
      }
    }
  }
}
```

Restart Claude Desktop afterward — it only reads this file on launch.

### Claude Code (CLI)

```bash
claude mcp add --transport stdio amocrm \
  -e AMO_SUBDOMAIN=your-subdomain \
  -e AMO_ACCESS_TOKEN=your-token \
  -- /absolute/path/to/amocrm-mcp/.venv/bin/python -m amocrm_mcp
```

Add `-s user` to make it available in every project instead of just the current one.

### Codex (CLI / Desktop)

Both read `~/.codex/config.toml`. Add:

```toml
[mcp_servers.amocrm]
command = "/absolute/path/to/amocrm-mcp/.venv/bin/python"
args = ["-m", "amocrm_mcp"]

[mcp_servers.amocrm.env]
AMO_SUBDOMAIN = "your-subdomain"
AMO_ACCESS_TOKEN = "your-token"
```

### Cursor

Add to `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` in the project (project-scoped) — same shape as Claude Desktop:

```json
{
  "mcpServers": {
    "amocrm": {
      "command": "/absolute/path/to/amocrm-mcp/.venv/bin/python",
      "args": ["-m", "amocrm_mcp"],
      "env": {
        "AMO_SUBDOMAIN": "your-subdomain",
        "AMO_ACCESS_TOKEN": "your-token"
      }
    }
  }
}
```

You can also do this from the UI: **Settings → MCP → Add new global MCP server**, which edits the same file.

## Tools

| Domain | Tools | Description |
|--------|-------|-------------|
| **Leads** | `leads_list`, `leads_get`, `leads_search`, `leads_create`, `leads_create_complex`, `leads_update` | Full lead lifecycle |
| **Contacts** | `contacts_get`, `contacts_search`, `contacts_create`, `contacts_update` | Contact management |
| **Companies** | `companies_get`, `companies_search`, `companies_create`, `companies_update` | Company management |
| **Tasks** | `tasks_list`, `tasks_get`, `tasks_create`, `tasks_update` | CRM task operations |
| **Notes** | `notes_list`, `notes_create` | Notes on entities |
| **Pipelines** | `pipelines_list`, `pipelines_get`, `pipelines_list_statuses` | Pipeline & status info |
| **Associations** | `associations_get_linked`, `associations_link_entities` | Entity relationships |
| **Account** | `account_get`, `account_list_users`, `account_list_custom_fields` | Account metadata |
| **Batch** | `batch_create_leads`, `batch_create_contacts`, `batch_update_leads` | Bulk operations |
| **Analytics** | `analytics_get_events`, `analytics_get_pipeline_analytics`, +1 | CRM analytics |
| **Unsorted** | `unsorted_list`, `unsorted_accept`, `unsorted_reject` | Unsorted inbox |

## Getting amoCRM Credentials

1. Go to your amoCRM account → **Settings** → **Integrations**
2. Create a new integration (or use an existing one)
3. Copy the **access token**, **client ID**, and **client secret**
4. Your subdomain is the part before `.amocrm.ru` in your account URL

## License

MIT
