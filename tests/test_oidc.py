"""login.oidc: config rules, who gets in, and the whole flow through a fake provider."""

import textwrap

import httpx
import pytest
from mcp_login_oauth import LoginRejected
from mcp_login_oauth.oidc import OidcClient
from starlette.testclient import TestClient

from examples import example
from fake_oidc import CLIENT_ID, CLIENT_SECRET, ISSUER, FakeProvider
from mcp_login_proxy.app import build_app
from mcp_login_proxy.config import Config, ConfigError, load_config
from mcp_login_proxy.login import build_hooks, upstream_headers
from test_app import BASE, REDIRECT, mcp, start_login

ENV = dict(OIDC_ISSUER=ISSUER, OIDC_CLIENT_ID=CLIENT_ID, OIDC_CLIENT_SECRET=CLIENT_SECRET)


def authentik(url="http://up"):
    return example("authentik", OPENBB_MCP_URL=f"{url}/mcp", **ENV)


def load(tmp_path, yaml):
    path = tmp_path / "proxy.yaml"
    path.write_text(textwrap.dedent(yaml))
    return load_config({"MCP_PROXY_CONFIG": str(path), "MCP_BASE_URL": BASE, "MCP_OAUTH_SECRET": "s", **ENV})


OIDC = """
service_name: X
upstream: http://up/mcp
login:
  oidc: {issuer: "${OIDC_ISSUER}", client_id: c, allowed_groups: [trading]}
"""


def test_example_loads():
    proxy = authentik()
    assert proxy.login.kind == "oidc" and proxy.login.oidc.allowed_groups == ["trading"] and proxy.fields == []


def test_oidc_needs_an_allow_list(tmp_path):
    with pytest.raises(ConfigError, match="allowed_groups or allowed_users"):
        load(tmp_path, OIDC.replace(", allowed_groups: [trading]", ""))


def test_oidc_refuses_fields_and_static_tokens(tmp_path):
    with pytest.raises(ConfigError, match="fields can't be used"):
        load(tmp_path, OIDC + "fields: [{name: password, label: P}]\n")
    with pytest.raises(ConfigError, match="static_tokens"):
        load(tmp_path, OIDC + "static_tokens: token\n")


def test_other_kinds_still_need_fields(tmp_path):
    with pytest.raises(ConfigError, match="at least one field"):
        load(tmp_path, "service_name: X\nupstream: http://up/mcp\nlogin: {upstream: {}}\n")


@pytest.mark.parametrize("claims, ok", [
    ({"preferred_username": "marcel", "groups": ["trading"]}, True),
    ({"preferred_username": "fabi", "groups": ["family", "trading"]}, True),
    ({"preferred_username": "bille", "groups": ["family"]}, False),
    ({"preferred_username": "bille"}, False),  # no groups claim: the profile scope wasn't granted
    ({"groups": ["trading"]}, False),  # no user name
])
async def test_who_gets_in(claims, ok):
    check = build_hooks(authentik(), httpx.AsyncClient()).check_login
    if ok:
        assert await check(claims) == {"user": claims["preferred_username"]}
    else:
        with pytest.raises(LoginRejected):
            await check(claims)


async def test_allowed_users_without_group(tmp_path):
    proxy = load(tmp_path, OIDC.replace("allowed_groups: [trading]", "allowed_users: [marcel]")).proxy
    assert await build_hooks(proxy, httpx.AsyncClient()).check_login({"preferred_username": "marcel"}) == {"user": "marcel"}


def test_user_header_upstream():
    assert upstream_headers(authentik(), {"user": "marcel"}) == [(b"x-forwarded-user", b"marcel")]


def test_whole_flow_through_a_fake_provider(trilium, tmp_path, monkeypatch):
    idp = FakeProvider()
    real_init = OidcClient.__init__
    monkeypatch.setattr(OidcClient, "__init__",
                        lambda self, login, transport=None: real_init(self, login, transport=httpx.MockTransport(idp.handler)))
    app = build_app(Config(proxy=authentik(trilium[0]), base_url=BASE, oauth_secret="s"), store_dir=tmp_path / "oauth",
                    failed_login_delay=0)
    with TestClient(app, base_url=BASE) as c:
        assert mcp(c, "").status_code == 401
        client_id, pending, verifier = start_login(c)
        assert "Continue with Authentik" in c.get("/login", params={"id": pending}).text
        r = c.post("/login", data={"id": pending}, follow_redirects=False)
        url = httpx.URL(r.headers["location"])
        idp.codes["code-1"] = url.params["nonce"]
        r = c.get("/login/callback", params={"code": "code-1", "state": url.params["state"]}, follow_redirects=False)
        code = httpx.URL(r.headers["location"]).params["code"]
        tokens = c.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                        "client_id": client_id, "code_verifier": verifier}).json()
        echoed = mcp(c, f"Bearer {tokens['access_token']}").json()
    assert echoed["headers"]["x-forwarded-user"] == "marcel" and "authorization" not in echoed["headers"]
