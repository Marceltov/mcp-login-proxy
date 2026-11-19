"""The app with the OpenBB (users) and OpenCloud (upstream) examples, the move from trilium-mcp-proxy,
the hash helper, and the rule that the code names no service."""

import base64
import re
from pathlib import Path

import httpx
import pytest
from argon2 import PasswordHasher
from mcp_login_oauth import LoginField, LoginOAuthProvider, build_store
from starlette.applications import Starlette
from starlette.testclient import TestClient

from examples import openbb, opencloud
from examples import trilium as trilium_example
from mcp_login_proxy import app as app_module
from mcp_login_proxy.app import build_app
from mcp_login_proxy.config import Config
from test_app import BASE, REDIRECT, mcp, start_login


def client_for(proxy, tmp_path):
    app = build_app(Config(proxy=proxy, base_url=BASE, oauth_secret="s"), store_dir=tmp_path / "oauth",
                    failed_login_delay=0)
    return TestClient(app, base_url=BASE)


def form_login(http, **form) -> httpx.Response:
    client_id, pending, verifier = start_login(http)
    r = http.post("/login", data={"id": pending, **form}, follow_redirects=False)
    r.client_id, r.verifier = client_id, verifier
    return r


def tokens_from(http, r) -> dict:
    code = httpx.URL(r.headers["location"]).params["code"]
    return http.post("/token", data={"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT,
                                     "client_id": r.client_id, "code_verifier": r.verifier}).json()


@pytest.fixture
def openbb_client(trilium, tmp_path):  # the fake Trilium's /mcp echoes requests: a fine stand-in upstream
    with client_for(openbb(trilium[0]), tmp_path) as c:
        yield c


def test_mcp_without_token_is_401(openbb_client):
    r = mcp(openbb_client, "")
    assert r.status_code == 401 and "resource_metadata" in r.headers["www-authenticate"]


def test_login_page_asks_user_and_password(openbb_client):
    _, pending, _ = start_login(openbb_client)
    page = openbb_client.get("/login", params={"id": pending}).text
    assert "OpenBB" in page and 'name="user"' in page and 'name="password"' in page


def test_login_then_forward_sends_no_authorization(openbb_client):
    r = form_login(openbb_client, user="fabi", password="fabi-pw")
    tokens = tokens_from(openbb_client, r)
    echoed = mcp(openbb_client, f"Bearer {tokens['access_token']}").json()
    assert "authorization" not in echoed["headers"]


def test_wrong_password_is_refused_on_the_form(openbb_client):
    r = form_login(openbb_client, user="marcel", password="fabi-pw")
    assert r.status_code != 302 and "Wrong user name or password." in r.text


def test_raw_token_is_401(openbb_client):
    assert mcp(openbb_client, "some-raw-token").status_code == 401
    assert mcp(openbb_client, "Bearer mlpx_made-up").status_code == 401


def test_opencloud_login_checks_upstream_and_forwards_basic(trilium, tmp_path):
    url, state = trilium
    state.reject_tokens = {"Basic " + base64.b64encode(b"alice:bad").decode()}
    with client_for(opencloud(url), tmp_path) as c:
        assert "refused these credentials" in form_login(c, user="alice", token="bad").text
        tokens = tokens_from(c, form_login(c, user="alice", token="t0k"))
        echoed = mcp(c, f"Bearer {tokens['access_token']}").json()
        assert echoed["headers"]["authorization"] == "Basic YWxpY2U6dDBr"


def test_token_from_old_store_still_works(trilium, tmp_path):
    """A login made through trilium-mcp-proxy 0.1.3 (its salt, prefix and grant) works after the move."""
    url, _ = trilium

    async def old_check(form):
        return {"etapi_token": "etapi-from-old"}
    old = LoginOAuthProvider(base_url=BASE, store=build_store(tmp_path / "oauth", secret="s",
                                                               salt="trilium-mcp-proxy-oauth"),
                             service_name="Trilium Notes",
                             fields=[LoginField("password", "Trilium password", type="password", required=True)],
                             check_login=old_check, token_prefix="tmpx_", failed_login_delay=0)
    with TestClient(Starlette(routes=old.get_routes(mcp_path="/mcp")), base_url=BASE) as c:
        tokens = tokens_from(c, form_login(c, password="pw"))
    assert tokens["access_token"].startswith("tmpx_")
    with client_for(trilium_example(url), tmp_path) as c:
        echoed = mcp(c, f"Bearer {tokens['access_token']}").json()
    assert echoed["headers"]["authorization"] == "etapi-from-old"


def test_hash_command_prints_a_verifiable_hash(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["mcp-login-proxy", "hash"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "s3cret")
    with pytest.raises(SystemExit) as exit_:
        app_module.main()
    hashed = capsys.readouterr().out.strip()
    assert exit_.value.code == 0 and hashed.startswith("$argon2id$")
    assert PasswordHasher().verify(hashed, "s3cret")


def test_hash_command_refuses_mismatch(monkeypatch):
    answers = iter(["one", "two"])
    monkeypatch.setattr("sys.argv", ["mcp-login-proxy", "hash"])
    monkeypatch.setattr("getpass.getpass", lambda prompt="": next(answers))
    with pytest.raises(SystemExit) as exit_:
        app_module.main()
    assert exit_.value.code == 1


def test_src_names_no_service():
    src = Path(__file__).parent.parent / "src"
    for path in src.rglob("*.py"):
        assert not re.search(r"trilium|openbb|opencloud", path.read_text(), re.I), path
