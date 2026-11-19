import httpx
import pytest
from mcp_login_oauth import LoginRejected

import mcp_login_proxy.login as login
from examples import openbb, opencloud, trilium
from mcp_login_proxy.login import WRONG_USER_OR_PASSWORD, build_hooks, grant_variables, upstream_headers

BASIC_ALICE = "Basic YWxpY2U6dDBr"  # alice:t0k


def opencloud_fake() -> httpx.AsyncClient:
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        ok = request.headers.get("authorization") == BASIC_ALICE
        return httpx.Response(200 if ok else 401, json={"jsonrpc": "2.0", "id": 0, "result": {}} if ok else {})
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client.seen = seen
    return client


async def test_users_mode_accepts_right_password():
    hooks = build_hooks(openbb("http://up"), httpx.AsyncClient())
    assert await hooks.check_login({"user": "marcel", "password": "marcel-pw"}) == {"user": "marcel"}


async def test_users_mode_grant_holds_no_password():
    grant = await build_hooks(openbb("http://up"), httpx.AsyncClient()).check_login(
        {"user": "fabi", "password": "fabi-pw"})
    assert "fabi-pw" not in repr(grant)


@pytest.mark.parametrize("form", [{"user": "marcel", "password": "fabi-pw"},
                                  {"user": "nobody", "password": "marcel-pw"},
                                  {"user": "Marcel", "password": "marcel-pw"},
                                  {"user": "marcel", "password": ""}])
async def test_users_mode_refuses_wrong_password_and_unknown_user(form):
    with pytest.raises(LoginRejected, match=WRONG_USER_OR_PASSWORD):
        await build_hooks(openbb("http://up"), httpx.AsyncClient()).check_login(form)


async def test_users_mode_strips_name():
    hooks = build_hooks(openbb("http://up"), httpx.AsyncClient())
    assert await hooks.check_login({"user": " marcel ", "password": "marcel-pw"}) == {"user": "marcel"}


async def test_unknown_user_is_verified_against_dummy_hash(monkeypatch):
    calls = []
    real = login._HASHER

    class Recording:
        def verify(self, h, p):
            calls.append(h)
            return real.verify(h, p)
    monkeypatch.setattr(login, "_HASHER", Recording())
    with pytest.raises(LoginRejected):
        await build_hooks(openbb("http://up"), httpx.AsyncClient()).check_login(
            {"user": "nobody", "password": "x"})
    assert calls == [login._DUMMY_HASH]


def test_users_mode_refuses_raw_token():
    hooks = build_hooks(openbb("http://up"), httpx.AsyncClient())
    assert hooks.verify_static is None
    assert hooks.on_revoke is None


async def test_upstream_mode_accepts_and_refuses():
    client = opencloud_fake()
    hooks = build_hooks(opencloud("http://oc"), client)
    assert await hooks.check_login({"user": "alice", "token": "t0k"}) == {"user": "alice", "token": "t0k"}
    assert client.seen[0].url == "http://oc/mcp"
    with pytest.raises(LoginRejected, match="HTTP 401"):
        await hooks.check_login({"user": "alice", "token": "bad"})


async def test_upstream_mode_unreachable_is_refused():
    def down(_):
        raise httpx.ConnectError("down")
    hooks = build_hooks(opencloud("http://oc"), httpx.AsyncClient(transport=httpx.MockTransport(down)))
    with pytest.raises(LoginRejected, match="unreachable"):
        await hooks.check_login({"user": "alice", "token": "t0k"})


async def test_exchange_mode_trilium_example(trilium):
    url, state = trilium
    async with httpx.AsyncClient() as client:
        hooks = build_hooks(trilium_config(url), client)
        assert await hooks.check_login({"password": "pw", "totp": ""}) == {"etapi_token": "etapi-1"}
        with pytest.raises(LoginRejected, match="^Wrong password.$"):
            await hooks.check_login({"password": "nope", "totp": ""})


async def test_exchange_without_totp_sends_no_totp_token(trilium):
    url, state = trilium
    async with httpx.AsyncClient() as client:
        await build_hooks(trilium_config(url), client).check_login({"password": "pw", "totp": ""})
    assert state.login_bodies == [{"password": "pw"}]


async def test_exchange_unmapped_refusal_names_the_status(trilium):
    url, state = trilium
    state.totp = "123456"
    config = trilium_config(url).model_copy(update={"messages": {}})
    async with httpx.AsyncClient() as client:
        with pytest.raises(LoginRejected, match="HTTP 401"):
            await build_hooks(config, client).check_login({"password": "pw", "totp": ""})


async def test_revoke_calls_logout(trilium):
    url, state = trilium
    async with httpx.AsyncClient() as client:
        await build_hooks(trilium_config(url), client).on_revoke({"etapi_token": "etapi-7"})
    assert state.logged_out == ["etapi-7"]


async def test_static_token_strips_bearer():
    hooks = build_hooks(trilium_config("http://t"), httpx.AsyncClient())
    assert await hooks.verify_static("Bearer abc") == {"etapi_token": "abc"}
    assert await hooks.verify_static("abc") == {"etapi_token": "abc"}


def test_upstream_headers_rendered_from_grant():
    assert upstream_headers(opencloud("http://oc"), {"user": "alice", "token": "t0k"}) == [
        (b"authorization", BASIC_ALICE.encode())]
    assert upstream_headers(openbb("http://up"), {"user": "marcel"}) == []
    assert upstream_headers(trilium_config("http://t"), {"etapi_token": "e"}) == [(b"authorization", b"e")]


def test_grant_keeps_only_what_is_used():
    assert grant_variables(trilium_config("http://t")) == {"etapi_token"}
    assert grant_variables(opencloud("http://oc")) == {"user", "token"}
    assert grant_variables(openbb("http://up")) == {"user"}


def trilium_config(url):
    return trilium(url)
