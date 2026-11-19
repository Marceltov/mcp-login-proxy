"""The three ways a login is checked, and what a grant turns into on each forwarded request.

- users: the form is checked against a fixed list of argon2id hashes; the grant is {"user": name}.
- upstream: the form's values, rendered into the upstream headers, are tried with one initialize request.
- exchange: the form is sent to a login URL, and a field of the JSON answer becomes a variable.

Passwords and tokens from the form are never logged.
"""

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from mcp_login_oauth import LoginRejected

from mcp_login_proxy.config import HttpRequest, ProxyConfig, grant_names, parse_users
from mcp_login_proxy.template import compute_vars, placeholders, render, render_json

log = logging.getLogger("mcp_login_proxy")

_HASHER = PasswordHasher()
# Checked for an unknown user name, so it takes as long as a wrong password and doesn't reveal names.
_DUMMY_HASH = _HASHER.hash("not a password anyone has")
WRONG_USER_OR_PASSWORD = "Wrong user name or password."

INITIALIZE = {"jsonrpc": "2.0", "id": 0, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                         "clientInfo": {"name": "mcp-login-proxy", "version": "login-check"}}}


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


@dataclass(frozen=True)
class LoginHooks:
    check_login: Callable[[dict], Awaitable[dict]]
    on_revoke: Callable[[dict], Awaitable[None]] | None
    verify_static: Callable[[str], Awaitable[dict | None]] | None


def grant_variables(proxy: ProxyConfig) -> set[str]:
    """What a grant keeps: only the names the upstream headers, vars and revoke use (plus the user name)."""
    used = placeholders(proxy.upstream_headers) | placeholders(proxy.vars)
    if proxy.revoke:
        used |= placeholders(proxy.revoke.model_dump())
    keep = used & grant_names(proxy)
    return keep | {"user"} if proxy.login.kind == "users" else keep


def upstream_headers(proxy: ProxyConfig, grant: dict) -> list[tuple[bytes, bytes]]:
    variables = compute_vars(proxy.vars, grant)
    return [(name.lower().encode("latin-1"), render(value, variables).encode("latin-1"))
            for name, value in proxy.upstream_headers.items()]


def form_values(proxy: ProxyConfig, form: dict) -> dict[str, str]:
    """The form's values by field; text fields are trimmed (a pasted code), passwords never are."""
    return {f.name: (v if f.type == "password" else v.strip())
            for f in proxy.fields for v in [form.get(f.name, "")]}


def _refusal(proxy: ProxyConfig, r: httpx.Response, field: str | None) -> str:
    code = None
    if field:
        try:
            code = r.json().get(field)
        except (ValueError, AttributeError):
            pass
    return proxy.messages.get(str(code)) if code is not None and str(code) in proxy.messages \
        else f"The login was refused (HTTP {r.status_code})."


async def _send(client: httpx.AsyncClient, request: HttpRequest, variables: dict) -> httpx.Response:
    return await client.request(request.method, render(request.url, variables),
                                headers={k: render(v, variables) for k, v in request.headers.items()},
                                json=render_json(request.json_body, variables)
                                if request.json_body is not None else None)


def build_hooks(proxy: ProxyConfig, client: httpx.AsyncClient) -> LoginHooks:
    keep = grant_variables(proxy)

    def trimmed(values: dict) -> dict:
        return {k: v for k, v in values.items() if k in keep}

    if proxy.login.kind == "users":
        users = parse_users(proxy.login.users or "")

        async def check_login(form: dict) -> dict:
            name, password = form.get("user", "").strip(), form.get("password", "")
            try:
                ok = _HASHER.verify(users.get(name, _DUMMY_HASH), password) and name in users
            except (VerificationError, InvalidHashError):
                ok = False
            if not ok:
                raise LoginRejected(WRONG_USER_OR_PASSWORD)
            return {"user": name}

    elif proxy.login.kind == "upstream":
        async def check_login(form: dict) -> dict:
            values = form_values(proxy, form)
            headers = [(k.decode(), v.decode()) for k, v in upstream_headers(proxy, values)]
            try:
                r = await client.post(proxy.upstream, json=INITIALIZE, headers=[
                    ("accept", "application/json, text/event-stream"), *headers])
            except httpx.HTTPError as e:
                log.warning("login check: the upstream is unreachable: %s", type(e).__name__)
                raise LoginRejected("The service is unreachable, try again later.") from None
            if not r.is_success:
                raise LoginRejected(f"The service refused these credentials (HTTP {r.status_code}).")
            return trimmed(values)

    else:
        exchange = proxy.login.exchange

        async def check_login(form: dict) -> dict:
            values = form_values(proxy, form)
            try:
                r = await _send(client, exchange.request, values)
            except httpx.HTTPError as e:
                log.warning("login check: the login URL is unreachable: %s", type(e).__name__)
                raise LoginRejected("The service is unreachable, try again later.") from None
            if not r.is_success:
                raise LoginRejected(_refusal(proxy, r, exchange.error))
            try:
                token = r.json()[exchange.token]
            except (ValueError, KeyError, TypeError):
                raise LoginRejected(f"The login answer holds no {exchange.token!r}.") from None
            return trimmed({**values, exchange.variable: str(token)})

    on_revoke = None
    if proxy.revoke:
        revoke = proxy.revoke

        async def on_revoke(grant: dict) -> None:
            await _send(client, revoke, compute_vars(proxy.vars, grant))

    verify_static = None
    if proxy.static_tokens:
        variable = proxy.static_tokens

        async def verify_static(token: str) -> dict | None:
            token = token.removeprefix("Bearer ").strip()
            return {variable: token} if token else None  # the upstream decides whether it's valid

    return LoginHooks(check_login=check_login, on_revoke=on_revoke, verify_static=verify_static)
