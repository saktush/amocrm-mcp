# Docker Deployment Guide (Streamable HTTP / network mode)

This guide covers running the amoCRM MCP server in Docker — either on your local machine with **Docker Desktop**, or on **any Linux server**. The container runs the server in **Streamable HTTP transport mode**, so it can be reached over the network by Claude, Codex, Cursor, and any other MCP client that supports Streamable HTTP (the modern standard transport for remote MCP servers, and the only one OpenAI Codex supports).

For the tool list, credential setup, and native (non-Docker) stdio usage with desktop clients like Claude Desktop, see the main [README.md](README.md).

## Prerequisites

- Docker Engine 24+ (Linux) or Docker Desktop (macOS/Windows), with the Compose v2 plugin (`docker compose`, bundled with both by default).
- An amoCRM (Kommo) OAuth access token, subdomain, and optionally client ID/secret + refresh token — see [Getting amoCRM Credentials](README.md#getting-amocrm-credentials) in the main README.

## Quick Start

```bash
cp .env.example .env
```

Edit `.env` and fill in at minimum:

- `AMO_SUBDOMAIN` — your amoCRM account subdomain
- `AMO_ACCESS_TOKEN` — OAuth access token

For automatic token refresh, also set `AMO_CLIENT_ID`, `AMO_CLIENT_SECRET`, `AMO_REFRESH_TOKEN`.

> Note: `docker-compose.yml` always runs the container in `http` (Streamable HTTP) transport mode regardless of what `AMO_TRANSPORT` is set to in `.env` — this is required for the container to be reachable over the network at all.

Build and start:

```bash
docker compose up -d --build
```

Confirm it started cleanly:

```bash
docker compose logs -f
```

You should see a line like:

```
amoCRM MCP server started with 36 tools on http transport
```

## Configuration Reference

| Variable | Required? | Default | Notes |
|---|---|---|---|
| `AMO_SUBDOMAIN` | **Yes** | — | amoCRM account subdomain. Missing this crashes the container at startup. |
| `AMO_ACCESS_TOKEN` | **Yes** | — | Initial OAuth access token (seed). Missing this crashes the container at startup. |
| `AMO_CLIENT_ID` | For auto-refresh | `""` | OAuth client ID |
| `AMO_CLIENT_SECRET` | For auto-refresh | `""` | OAuth client secret |
| `AMO_REFRESH_TOKEN` | For auto-refresh | `""` | OAuth refresh token (seed) |
| `AMO_TOKEN_FILE` | No | Fixed to `/data/.amo_tokens.json` by Docker setup | Where refreshed tokens are persisted. Overridable, but must point inside `/data` to survive container recreation. |
| `AMO_TRANSPORT` | No | Fixed to `http` by Docker setup | Streamable HTTP (modern standard, required by Codex). `sse` (legacy) is also available — see [Advanced: stdio](#advanced-stdio-inside-a-container-discouraged) for how to override. |
| `AMO_PORT` | No | `8000` | Also controls the published host port (`docker-compose.yml` maps `${AMO_PORT}:${AMO_PORT}`). |

## Connecting an MCP Client

The server is reachable at:

```
http://<host>:<AMO_PORT>/mcp
```

- `<host>` is `localhost` for a local Docker Desktop setup, or the server's hostname/IP for a remote Linux deployment.
- Note the **`/mcp`** path suffix — FastMCP's Streamable HTTP endpoint is not served at the bare host:port.
- Only MCP clients that support **Streamable HTTP** (or legacy SSE — see below) can connect to a containerized deployment. Stdio-based clients (e.g. Claude Desktop's default `claude_desktop_config.json` entries) need the native `.venv` setup described in the main [README.md](README.md) instead.

**Security note:** there is no transport-level authentication beyond the amoCRM tokens the server holds internally. Do not expose `0.0.0.0:<port>` directly to the public internet on a Linux server — put it behind a VPN/private network, or a TLS-terminating reverse proxy (nginx, Caddy, Traefik).

### Claude Desktop

`claude_desktop_config.json` only supports stdio servers — you cannot add a remote URL there. Instead, add it as a **custom connector**:

1. Open Claude Desktop → **Settings → Connectors → Add custom connector**.
2. Enter the URL: `http://<host>:<AMO_PORT>/mcp`
3. Save. Claude Desktop connects over Streamable HTTP directly — no JSON editing needed.

### Claude Code (CLI)

```bash
claude mcp add --transport http amocrm http://<host>:8000/mcp
```

Add `-s user` to make it available in every project instead of just the current one. (`--transport sse` also works against the legacy `/sse` endpoint if you've overridden `AMO_TRANSPORT=sse`, but `http` is recommended.)

### Codex (CLI / Desktop)

Codex **only** supports stdio and Streamable HTTP for MCP servers — it does not support SSE. Edit `~/.codex/config.toml`:

```toml
[mcp_servers.amocrm]
url = "http://<host>:8000/mcp"
```

### Cursor

Add to `~/.cursor/mcp.json` (global) or `.cursor/mcp.json` in the project (project-scoped):

```json
{
  "mcpServers": {
    "amocrm": {
      "url": "http://<host>:8000/mcp"
    }
  }
}
```

You can also do this from the UI: **Settings → MCP → Add new global MCP server**, which edits the same file.

### Legacy SSE clients

If a client only supports the older SSE transport (not Streamable HTTP), you need to override `AMO_TRANSPORT`. Setting a shell environment variable before `docker compose up` has **no effect** — `docker-compose.yml` sets `AMO_TRANSPORT: http` as a fixed value, not a `${AMO_TRANSPORT}` substitution, specifically so a stray `AMO_TRANSPORT=stdio` left in `.env` (the `.env.example` default) can't accidentally break the network deployment.

- **One-off test**, without touching `docker-compose.yml`:
  ```bash
  docker compose run --rm -e AMO_TRANSPORT=sse -p 8000:8000 amocrm-mcp
  ```
- **Persistent SSE deployment**: edit `docker-compose.yml` and change `AMO_TRANSPORT: http` to `AMO_TRANSPORT: sse` under the service's `environment:` key, then `docker compose up -d --build`.

Either way, connect the client to `http://<host>:8000/sse` instead of `/mcp`. SSE is being phased out across the MCP ecosystem in favor of Streamable HTTP, so prefer `/mcp` unless a specific client requires it.

## Persistent Token Storage

Refreshed OAuth tokens are written to `/data/.amo_tokens.json` inside the container, which is backed by the `amo_tokens` named Docker volume declared in `docker-compose.yml`. This is what lets refreshed tokens survive container restarts/recreation — without it, the server would fall back to the (possibly stale) env-seeded `AMO_ACCESS_TOKEN` every time the container is recreated.

To inspect the persisted token file:

```bash
docker compose exec amocrm-mcp cat /data/.amo_tokens.json
```

**`docker compose down -v` deletes this volume** (and the persisted tokens) — use plain `docker compose down` (no `-v`) if you want to keep them.

If you'd prefer the token file to be directly visible on the host filesystem instead of inside a named volume, you can swap the `amo_tokens:/data` volume mapping for a bind mount (e.g. `./data:/data`). On a native Linux host you'll then need to `chown 1000:1000 ./data` first, since the container runs as uid 1000 and bind mounts keep host-side ownership (unlike named volumes, which Docker manages internally).

## Viewing Logs

```bash
docker compose logs -f amocrm-mcp
```

The app logs to stderr, which Docker captures the same as stdout — no extra configuration needed.

## Updating / Rebuilding

```bash
git pull
docker compose up -d --build
```

Images aren't pushed to a registry in this setup — each host rebuilds from source.

## Running on a Remote Linux Server

The exact same commands as above work unchanged on any Linux server, since Compose files are portable. The only Linux-specific setup steps are:

1. Install Docker Engine and the Compose plugin (official convenience script or your distro's packages).
2. Open the chosen port in your firewall / cloud security group, e.g.:
   ```bash
   sudo ufw allow 8000/tcp
   ```

## Advanced: stdio Inside a Container (discouraged)

Running the server in `stdio` mode inside a container is possible but not a normal MCP workflow — it ties the container's lifecycle to a client subprocess model it wasn't designed for, and adds startup latency. If you need this:

```bash
docker compose run --rm -i -e AMO_TRANSPORT=stdio amocrm-mcp
```

(`-i` keeps stdin open, which stdio transport requires — without it the client has nothing to write to.)

For local desktop-client use (Claude Desktop, Cursor, etc.), prefer the native `.venv` + stdio setup documented in the main [README.md](README.md) instead — it's simpler and is what those clients expect.

## Troubleshooting

- **Container exits immediately, logs show a pydantic `ValidationError` mentioning `subdomain` or `access_token`** — `AMO_SUBDOMAIN`/`AMO_ACCESS_TOKEN` are missing from `.env`, or `docker compose` was run from a directory where `.env` isn't next to `docker-compose.yml`.
- **`docker compose ps` shows `unhealthy`** — expected/cosmetic if you've overridden `AMO_TRANSPORT=stdio` (the healthcheck probes the HTTP port, which isn't bound in stdio mode). Plain Docker does not restart containers based on health status alone.
- **Codex reports it can't connect / only stdio and Streamable HTTP are supported** — make sure you're using the default `AMO_TRANSPORT=http` (not `sse`) and the URL ends in `/mcp`, not `/sse`. Codex does not support the legacy SSE transport at all.
- **MCP client reports "connection refused"** — check `docker compose ps` shows `Up`, confirm the published port matches `AMO_PORT`, and check the host firewall.
- **Refreshed tokens aren't persisting across restarts** — confirm `AMO_TOKEN_FILE` still points inside `/data` (the volume mount point); if you overrode it elsewhere, it won't survive container recreation.

## See Also

- [README.md](README.md) — full tool list, credential setup, and native stdio usage with Claude Desktop / Claude Code / Codex / Cursor.
