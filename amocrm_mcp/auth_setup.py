"""One-time OAuth bootstrap: obtain the first access/refresh token pair.

Usage:
    amocrm-mcp-auth [--env-file .env] [--code CODE] [--port 8765] [--no-browser]

Needs AMO_SUBDOMAIN, AMO_CLIENT_ID, AMO_CLIENT_SECRET and AMO_REDIRECT_URI (the redirect URI
must match the integration settings exactly). Either pass the authorization code shown on the
integration's "Keys and access" tab (--code, valid 20 minutes, single use), or let the script
open the consent page and catch the redirect on a local http://localhost:<port>/ URL.
Tokens are written to AMO_TOKEN_FILE and never printed.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from amocrm_mcp.auth import AuthError, AuthManager
from amocrm_mcp.config import Config

LOCAL_HOSTS = ("localhost", "127.0.0.1")


def authorize_url(config: Config, state: str) -> str:
    query = urlencode({"client_id": config.client_id, "state": state, "mode": "post_message"})
    return f"https://www.{config.base_domain}/oauth?{query}"


def parse_callback(path: str, state: str) -> str:
    """Return the authorization code from a redirect path, validating state."""
    params = parse_qs(urlparse(path).query)
    if params.get("state", [""])[0] != state:
        raise AuthError("OAuth state mismatch; ignoring the callback")
    if "error" in params:
        raise AuthError(f"Authorization denied: {params['error'][0]}")
    code = params.get("code", [""])[0]
    if not code:
        raise AuthError("Callback did not contain an authorization code")
    return code


def wait_for_code(redirect_uri: str, state: str, port: int, timeout: float = 300.0) -> str:
    """Serve the redirect URI locally until the callback arrives."""
    parsed = urlparse(redirect_uri)
    if parsed.hostname not in LOCAL_HOSTS:
        raise AuthError(
            f"redirect_uri {redirect_uri} is not local; use --code with the authorization code instead"
        )
    port = parsed.port or port
    result: dict[str, object] = {}
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            try:
                result["code"] = parse_callback(self.path, state)
                body, status = b"Authorization received. You can close this tab.", 200
            except AuthError as exc:
                result["error"] = exc
                body, status = str(exc).encode(), 400
            self.send_response(status)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            if status == 200:
                done.set()

        def log_message(self, *args: object) -> None:  # keep the code out of logs
            pass

    server = HTTPServer((parsed.hostname, port), Handler)
    server.timeout = 1.0
    deadline = threading.Timer(timeout, done.set)
    deadline.start()
    try:
        while not done.is_set():
            server.handle_request()
    finally:
        deadline.cancel()
        server.server_close()
    if "code" not in result:
        raise AuthError(str(result.get("error", "Timed out waiting for the OAuth callback")))
    return result["code"]  # type: ignore[return-value]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="amocrm-mcp-auth", description=__doc__.split("\n\n")[0])
    ap.add_argument("--env-file", default=".env")
    ap.add_argument("--code", help="authorization code from the integration's Keys and access tab")
    ap.add_argument("--port", type=int, default=8765, help="local callback port if redirect_uri has none")
    ap.add_argument("--no-browser", action="store_true", help="print the consent URL instead of opening it")
    args = ap.parse_args(argv)

    config = Config(_env_file=args.env_file)
    missing = [n for n in ("client_id", "client_secret") if not getattr(config, n)]
    if missing:
        print(f"Missing AMO_{', AMO_'.join(m.upper() for m in missing)} in {args.env_file}", file=sys.stderr)
        return 2

    try:
        code = args.code
        if not code:
            state = secrets.token_urlsafe(16)
            url = authorize_url(config, state)
            print(f"Redirect URI: {config.redirect_uri} (must match the integration settings)")
            print(f"Open this URL and grant access:\n  {url}")
            if not args.no_browser:
                webbrowser.open(url)
            code = wait_for_code(config.redirect_uri, state, args.port)
        asyncio.run(AuthManager(config).exchange_code(code))
    except AuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"Tokens saved to {config.token_file}. Keep AMO_CLIENT_ID/AMO_CLIENT_SECRET set so they auto-refresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
