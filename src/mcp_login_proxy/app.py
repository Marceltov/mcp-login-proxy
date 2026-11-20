"""The proxy app: OAuth login (mcp-login-oauth), the auth gate on /mcp, /health, and the hash helper.

Everything about the upstream (the login form, how a login is checked, what is added to each request)
comes from the config file; see config.py and login.py.
"""

import contextlib
import getpass
import logging
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastmcp.server.auth.middleware import RequireAuthMiddleware
from mcp.server.auth.routes import build_resource_metadata_url
from mcp_login_oauth import BearerPrefixMiddleware, LoginOAuthProvider, OidcLogin, build_store
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from mcp_login_proxy.config import Config, ConfigError, load_config
from mcp_login_proxy.forward import Forwarder
from mcp_login_proxy.login import build_hooks, hash_password, upstream_headers

log = logging.getLogger("mcp_login_proxy")

MCP_PATH = "/mcp"


def build_provider(config: Config, client: httpx.AsyncClient, store_dir: Path, **overrides) -> LoginOAuthProvider:
    proxy = config.proxy
    hooks = build_hooks(proxy, client)
    args = dict(base_url=config.base_url,
                store=build_store(store_dir, secret=config.oauth_secret, salt=proxy.store_salt),
                service_name=proxy.service_name,
                fields=[f.to_login_field() for f in proxy.fields],
                check_login=hooks.check_login, on_revoke=hooks.on_revoke, verify_static=hooks.verify_static,
                token_prefix=proxy.token_prefix)
    if oidc := proxy.login.oidc:
        args["oidc"] = OidcLogin(issuer=oidc.issuer, client_id=oidc.client_id, client_secret=oidc.client_secret,
                                 scopes=tuple(oidc.scopes), name=oidc.name, verify_tls=oidc.verify_tls,
                                 pass_access_token=oidc.credential is not None)
    return LoginOAuthProvider(**{**args, **overrides})


def build_app(config: Config, store_dir: Path = Path("/data/oauth"),
              transport: httpx.AsyncBaseTransport | None = None, **provider_overrides):
    """`transport` and `provider_overrides` are for tests (a fake upstream, failed_login_delay=0)."""
    proxy = config.proxy
    parts = urlsplit(proxy.upstream)
    # No total timeout: event streams and long tool calls stay open as long as the upstream keeps them.
    client = httpx.AsyncClient(base_url=f"{parts.scheme}://{parts.netloc}", transport=transport,
                               timeout=httpx.Timeout(connect=10, read=None, write=60, pool=10))
    provider = build_provider(config, client, store_dir, **provider_overrides)
    metadata_url = build_resource_metadata_url(AnyHttpUrl(config.base_url + MCP_PATH))
    forwarder = Forwarder(client, parts.path or "/", lambda grant: upstream_headers(proxy, grant),
                          proxy.instructions)
    gate = RequireAuthMiddleware(forwarder, provider.required_scopes or [], metadata_url)

    async def health(_: Request) -> JSONResponse:
        if not proxy.health:
            return JSONResponse({"status": "ok"})
        try:
            ok = (await client.get(proxy.health, timeout=5)).is_success
        except httpx.HTTPError:
            ok = False
        return JSONResponse({"status": "ok", "upstream": "ok" if ok else "unreachable"})

    @contextlib.asynccontextmanager
    async def lifespan(_):
        yield
        await client.aclose()

    app = Starlette(routes=[*provider.get_routes(mcp_path=MCP_PATH), Route("/health", health),
                            Route(MCP_PATH, gate, methods=["GET", "POST", "DELETE"])],
                    middleware=provider.get_middleware(), lifespan=lifespan)
    return BearerPrefixMiddleware(app)


def hash_command() -> int:
    """`mcp-login-proxy hash`: read a password twice without echo and print its argon2id hash."""
    password = getpass.getpass("Password: ")
    if not password:
        print("mcp-login-proxy: the password is empty", file=sys.stderr)
        return 1
    if getpass.getpass("Again: ") != password:
        print("mcp-login-proxy: the passwords differ", file=sys.stderr)
        return 1
    print(hash_password(password))
    return 0


def main() -> None:
    if sys.argv[1:] == ["hash"]:
        sys.exit(hash_command())
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        config = load_config(os.environ)
    except ConfigError as e:
        print(f"mcp-login-proxy: {e}", file=sys.stderr)
        sys.exit(1)
    import uvicorn
    uvicorn.run(build_app(config), host="0.0.0.0", port=config.port, log_level="warning")
