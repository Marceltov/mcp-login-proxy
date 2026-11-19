"""Configuration: a few environment variables, and one YAML file for everything about the upstream.

The file (MCP_PROXY_CONFIG, default /config/proxy.yaml) says what the login form asks, how a login is
checked, and what the proxy adds to each request it forwards. `${NAME}` in it is replaced from the
environment when it's loaded, so secrets stay out of the file. See docs/configuration.md.
"""

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from mcp.server.auth.routes import validate_issuer_url
from mcp_login_oauth import LoginField
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, model_validator

from mcp_login_proxy.template import VAR_FUNCTIONS, placeholders


class ConfigError(Exception):
    pass


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class FormField(_Strict):
    name: str
    label: str
    type: Literal["text", "password", "email"] = "text"
    required: bool = False
    autocomplete: str | None = None
    hint: str | None = None

    def to_login_field(self) -> LoginField:
        return LoginField(self.name, self.label, type=self.type, required=self.required,
                          autocomplete=self.autocomplete, hint=self.hint)


class HttpRequest(_Strict):
    method: str = "POST"
    url: str
    headers: dict[str, str] = {}
    json_body: dict[str, Any] | None = Field(default=None, alias="json")


class Exchange(_Strict):
    request: HttpRequest
    token: str  # the JSON field of the answer that holds the token
    variable: str = "token"  # the variable it becomes, e.g. {token}
    error: str | None = None  # the JSON field of a refusal, looked up in `messages`


class Credential(_Strict):
    """After the sign-in, one request with the provider's access token ({access_token}) and the user name
    ({user}) whose JSON answer holds the upstream's credential, e.g. an app token."""
    request: HttpRequest
    token: str  # the JSON field of the answer that holds the credential
    variable: str = "token"  # the variable it becomes, e.g. {token}


CREDENTIAL_INPUTS = {"access_token", "user"}


class Oidc(_Strict):
    issuer: str  # exactly as the provider publishes it; Authentik: https://<host>/application/o/<slug>/
    client_id: str
    client_secret: str | None = None
    name: str = "single sign-on"  # "Continue with <name>"
    scopes: list[str] = ["openid", "profile", "email"]
    user_claim: str = "preferred_username"
    allowed_groups: list[str] = []
    allowed_users: list[str] = []
    verify_tls: bool = True
    credential: Credential | None = None


class Login(_Strict):
    users: str | None = None
    upstream: dict[str, Any] | None = None
    exchange: Exchange | None = None
    oidc: Oidc | None = None

    @model_validator(mode="before")
    @classmethod
    def _empty_users_is_a_list(cls, data):
        # `users: ${USERS}` with an empty variable is YAML null; it's an empty list, not a missing key.
        if isinstance(data, dict) and "users" in data and data["users"] is None:
            return {**data, "users": ""}
        return data

    @model_validator(mode="after")
    def _exactly_one(self):
        if sum(x is not None for x in (self.users, self.upstream, self.exchange, self.oidc)) != 1:
            raise ValueError("login needs exactly one of users, upstream, exchange or oidc")
        return self

    @property
    def kind(self) -> Literal["users", "upstream", "exchange", "oidc"]:
        for kind in ("users", "upstream", "exchange", "oidc"):
            if getattr(self, kind) is not None:
                return kind
        raise AssertionError("validated: exactly one login kind")


class ProxyConfig(_Strict):
    service_name: str
    upstream: str
    instructions: str | None = None
    fields: list[FormField] = []  # the login form; none with login.oidc
    login: Login
    messages: dict[str, str] = {}
    revoke: HttpRequest | None = None
    static_tokens: str | None = None  # the variable a raw token in the Authorization header becomes
    vars: dict[str, dict[str, str]] = {}
    upstream_headers: dict[str, str] = {}
    health: str | None = None
    token_prefix: str = "mlpx_"
    store_salt: str = "mcp-login-proxy-oauth"


@dataclass(frozen=True)
class Config:
    proxy: ProxyConfig
    base_url: str  # MCP_BASE_URL: the public URL, and the OAuth issuer
    oauth_secret: str  # MCP_OAUTH_SECRET: encrypts the OAuth store
    port: int = 8081


def parse_users(raw: str) -> dict[str, str]:
    """`name:hash` entries separated by whitespace (argon2 hashes contain commas, never spaces)."""
    users = {}
    for entry in raw.split():
        name, sep, hashed = entry.partition(":")
        if not sep or not name or not hashed:
            raise ConfigError(f"login.users: {entry[:12]!r}… is not name:hash")
        users[name] = hashed
    return users


def _required(env: Mapping[str, str], name: str, why: str) -> str:
    value = env.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set: {why}")
    return value


_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _substitute(text: str, env: Mapping[str, str]) -> str:
    def one(m: re.Match) -> str:
        if m.group(1) not in env:
            raise ConfigError(f"the config file references ${{{m.group(1)}}}, which is not set")
        return env[m.group(1)]
    return _ENV_REF.sub(one, text)


def grant_names(proxy: ProxyConfig) -> set[str]:
    """The variables a grant may hold: what a login produces, before `vars` are derived."""
    if proxy.login.kind == "oidc":
        # never the provider's tokens: only the credential they bought, if any
        credential = proxy.login.oidc.credential
        return {"user", credential.variable} if credential else {"user"}
    if proxy.login.kind == "users":
        return {"user"}  # never the password: the upstream doesn't need it
    names = {f.name for f in proxy.fields}
    if proxy.login.kind == "exchange":
        names.add(proxy.login.exchange.variable)
    if proxy.static_tokens:
        names.add(proxy.static_tokens)
    return names


def _check(proxy: ProxyConfig) -> None:
    if proxy.login.kind == "oidc":
        oidc = proxy.login.oidc
        if proxy.fields:
            raise ConfigError("fields can't be used with login.oidc: the provider asks who you are")
        if proxy.static_tokens:
            raise ConfigError("static_tokens can't be used with login.oidc: only someone the provider signed in "
                              "may get through")
        if not oidc.allowed_groups and not oidc.allowed_users:
            raise ConfigError("login.oidc needs allowed_groups or allowed_users: otherwise everyone with an "
                              "account at the provider would get in")
    elif not proxy.fields:
        raise ConfigError("fields is empty: the login form needs at least one field")
    if proxy.login.kind == "users":
        if proxy.static_tokens:
            raise ConfigError("static_tokens can't be used with login.users: the upstream has no login of its "
                              "own, so a raw token would let anyone in")
        users = parse_users(proxy.login.users or "")
        if not users:
            raise ConfigError("login.users holds no users")
        for name, hashed in users.items():
            if not hashed.startswith("$argon2id$"):
                raise ConfigError(f"login.users: the hash for {name!r} is not argon2id "
                                  "(make one with `mcp-login-proxy hash`)")
    known = grant_names(proxy)
    for name, definition in proxy.vars.items():
        if len(definition) != 1 or next(iter(definition)) not in VAR_FUNCTIONS:
            raise ConfigError(f"vars.{name}: one of {sorted(VAR_FUNCTIONS)} expected, e.g. "
                              '{base64: "{user}:{token}"}')
        _known(f"vars.{name}", definition, known)
        known = known | {name}
    _known("upstream_headers", proxy.upstream_headers, known)
    if proxy.revoke:
        _known("revoke", proxy.revoke.model_dump(), known)
    if proxy.login.oidc and proxy.login.oidc.credential:
        _known("login.oidc.credential.request", proxy.login.oidc.credential.request.model_dump(), CREDENTIAL_INPUTS)
    if proxy.login.exchange:
        _known("login.exchange.request", proxy.login.exchange.request.model_dump(),
               {f.name for f in proxy.fields})


def _known(where: str, value: Any, known: set[str]) -> None:
    try:
        names = placeholders(value)
    except ValueError as e:
        raise ConfigError(f"{where}: {e}") from None
    if unknown := names - known:
        raise ConfigError(f"{where} uses {', '.join('{' + n + '}' for n in sorted(unknown))}, which is "
                          f"not defined here (known: {', '.join(sorted(known)) or 'none'})")


def load_proxy_config(path: Path, env: Mapping[str, str]) -> ProxyConfig:
    try:
        text = path.read_text()
    except OSError as e:
        raise ConfigError(f"can't read the config file {path} (MCP_PROXY_CONFIG): {e.strerror}") from None
    try:
        data = yaml.safe_load(_substitute(text, env))
    except yaml.YAMLError as e:
        raise ConfigError(f"{path} is not valid YAML: {e}") from None
    try:
        proxy = ProxyConfig.model_validate(data or {})
    except ValidationError as e:
        problems = "; ".join(f"{'.'.join(map(str, err['loc'])) or 'file'}: {err['msg']}" for err in e.errors())
        raise ConfigError(f"{path}: {problems}") from None
    _check(proxy)
    return proxy


def load_config(env: Mapping[str, str] = os.environ) -> Config:
    base_url = _required(env, "MCP_BASE_URL", "the proxy's public URL, which is also the OAuth issuer, "
                         "e.g. https://mcp-login-proxy.example").rstrip("/")
    try:
        validate_issuer_url(AnyHttpUrl(base_url))
    except ValueError as e:
        raise ConfigError(f"MCP_BASE_URL={base_url!r} is not a valid OAuth issuer "
                          f"(https, no query or fragment; plain http only for localhost): {e}") from None
    secret = _required(env, "MCP_OAUTH_SECRET", "it encrypts the stored logins; generate one with "
                       "`openssl rand -hex 32`")
    raw_port = env.get("MCP_PORT", "").strip() or "8081"
    try:
        port = int(raw_port)
    except ValueError:
        raise ConfigError(f"MCP_PORT must be an integer, got {raw_port!r}") from None
    path = Path(env.get("MCP_PROXY_CONFIG", "").strip() or "/config/proxy.yaml")
    return Config(proxy=load_proxy_config(path, env), base_url=base_url, oauth_secret=secret, port=port)
