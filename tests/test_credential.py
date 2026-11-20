"""login.oidc.credential: after the sign-in, the provider's access token buys the upstream's credential."""

import base64
import textwrap

import httpx
import pytest
from mcp_login_oauth import LoginRejected
from mcp_login_oauth.oidc import OidcClient
from starlette.testclient import TestClient

from examples import example
from fake_oidc import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeProvider
from mcp_login_proxy.app import build_app, build_provider
from mcp_login_proxy.config import Config, ConfigError, load_config
from mcp_login_proxy.login import build_hooks, grant_variables
from test_app import BASE, REDIRECT, mcp, start_login

ENV = dict(OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID=CLIENT_ID, OIDC_CLIENT_SECRET=CLIENT_SECRET)
CLAIMS = {"preferred_username": "marcel", "groups": ["opencloud-users"], "access_token": "at"}


def opencloud_oidc(url="http://oc"):
    return example("opencloud-oidc", OPENCLOUD_MCP_URL=f"{url}/mcp", OPENCLOUD_URL=url, **ENV)


def cloud(seen: list, status=200, answer=None):
    """A fake OpenCloud: /auth-app/tokens makes an app token for a bearer token, /mcp echoes the headers."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/auth-app/tokens":
            seen.append(request)
            return httpx.Response(status, json=answer if answer is not None else
                                  {"token": "app-token-1", "label": "Claude", "expiration_date": "2027-02-17"})
        return httpx.Response(200, json={"headers": dict(request.headers)})
    return httpx.MockTransport(handler)


def test_example_loads_and_keeps_only_user_and_token():
    proxy = opencloud_oidc()
    assert proxy.login.oidc.credential.variable == "token"
    assert grant_variables(proxy) == {"user", "token"}


async def test_the_access_token_buys_an_app_token():
    seen = []
    check = build_hooks(opencloud_oidc(), httpx.AsyncClient(transport=cloud(seen))).check_login
    assert await check(dict(CLAIMS)) == {"user": "marcel", "token": "app-token-1"}
    sent = seen[0]
    assert sent.method == "POST" and sent.headers["authorization"] == "Bearer at"
    assert str(sent.url) == "http://oc/auth-app/tokens?expiry=2160h&label=Claude"


async def test_who_may_not_get_in_buys_nothing():
    seen = []
    check = build_hooks(opencloud_oidc(), httpx.AsyncClient(transport=cloud(seen))).check_login
    with pytest.raises(LoginRejected, match="may not use"):
        await check({**CLAIMS, "groups": ["family"]})
    assert seen == []


@pytest.mark.parametrize("status, answer, message", [
    (401, {}, "refused"),
    (200, {"label": "no token here"}, "holds no 'token'"),
    (200, [], "holds no 'token'"),
])
async def test_a_refused_or_odd_answer_is_shown(status, answer, message):
    check = build_hooks(opencloud_oidc(), httpx.AsyncClient(transport=cloud([], status, answer))).check_login
    with pytest.raises(LoginRejected, match=message):
        await check(dict(CLAIMS))


async def test_an_unreachable_service_is_named():
    def down(_):
        raise httpx.ConnectError("down")
    check = build_hooks(opencloud_oidc(), httpx.AsyncClient(transport=httpx.MockTransport(down))).check_login
    with pytest.raises(LoginRejected, match="unreachable"):
        await check(dict(CLAIMS))


def test_the_provider_is_asked_for_the_access_token(tmp_path):
    provider = build_provider(Config(proxy=opencloud_oidc(), base_url=BASE, oauth_secret="s"), httpx.AsyncClient(),
                              tmp_path / "oauth")
    assert provider.oidc.pass_access_token
    plain = example("authentik", OPENBB_MCP_URL="http://up/mcp", **ENV)
    provider = build_provider(Config(proxy=plain, base_url=BASE, oauth_secret="s"), httpx.AsyncClient(), tmp_path / "o2")
    assert not provider.oidc.pass_access_token  # without a credential, nothing from the provider is passed on


def load(tmp_path, yaml):
    path = tmp_path / "proxy.yaml"
    path.write_text(textwrap.dedent(yaml))
    return load_config({"MCP_PROXY_CONFIG": str(path), "MCP_BASE_URL": BASE, "MCP_OAUTH_SECRET": "s", **ENV})


def test_the_request_may_use_only_the_access_token_and_user(tmp_path):
    yaml = """
    service_name: X
    upstream: http://up/mcp
    login:
      oidc:
        issuer: "${OIDC_ISSUER}"
        client_id: c
        allowed_users: [marcel]
        credential: {request: {url: "http://up/t?u={user}&p={password}"}, token: token}
    upstream_headers: {Authorization: "Bearer {token}"}
    """
    with pytest.raises(ConfigError, match=r"login.oidc.credential.request uses \{password\}"):
        load(tmp_path, yaml)
    assert load(tmp_path, yaml.replace("&p={password}", "")).proxy.login.oidc.credential.token == "token"


class AppTokensThenReal(httpx.AsyncBaseTransport):
    """/auth-app/tokens from the fake OpenCloud; every other request to the real (fake Trilium) server, which
    echoes the headers it got: in-process transports buffer and break the proxy's streaming."""

    def __init__(self, seen: list):
        self.tokens, self.real = cloud(seen), httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request):
        if request.url.path == "/auth-app/tokens":
            return await self.tokens.handle_async_request(request)
        return await self.real.handle_async_request(request)


def test_whole_flow_signs_in_once_and_forwards_the_app_token(trilium, tmp_path, monkeypatch):
    idp = FakeProvider()
    idp.claims["groups"] = ["opencloud-users"]
    real_init = OidcClient.__init__
    monkeypatch.setattr(OidcClient, "__init__",
                        lambda self, login, transport=None: real_init(self, login, transport=httpx.MockTransport(idp.handler)))
    seen = []
    app = build_app(Config(proxy=opencloud_oidc(trilium[0]), base_url=BASE, oauth_secret="s"), store_dir=tmp_path / "oauth",
                    transport=AppTokensThenReal(seen), failed_login_delay=0)
    with TestClient(app, base_url=BASE) as c:
        client_id, pending, verifier = start_login(c)
        r = c.post("/login", data={"id": pending}, follow_redirects=False)
        url = httpx.URL(r.headers["location"])
        assert set(url.params["scope"].split()) == {"openid", "profile", "email", "roles"}
        idp.codes["code-1"] = url.params["nonce"]
        r = c.get("/login/callback", params={"code": "code-1", "state": url.params["state"]}, follow_redirects=False)
        code = httpx.URL(r.headers["location"]).params["code"]
        tokens = c.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                        "client_id": client_id, "code_verifier": verifier}).json()
        assert "refresh_token" in tokens
        echoed = mcp(c, f"Bearer {tokens['access_token']}").json()
        refreshed = c.post("/token", data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"],
                                           "client_id": client_id}).json()
        again = mcp(c, f"Bearer {refreshed['access_token']}").json()
    basic = "Basic " + base64.b64encode(b"marcel:app-token-1").decode()
    assert echoed["headers"]["authorization"] == basic and again["headers"]["authorization"] == basic
    assert len(seen) == 1  # one app token per sign-in, not per request or refresh
