import textwrap

import pytest
from argon2 import PasswordHasher

from mcp_login_proxy.config import Config, ConfigError, load_config, parse_users

HASH = PasswordHasher().hash("pw")

USERS = """
service_name: OpenBB
upstream: http://mcp:8001/mcp
fields:
  - {name: user, label: User, required: true}
  - {name: password, label: Password, type: password, required: true}
login:
  users: ${USERS}
"""


@pytest.fixture
def env(tmp_path):
    def make(yaml: str, **extra) -> dict:
        path = tmp_path / "proxy.yaml"
        path.write_text(textwrap.dedent(yaml))
        return {"MCP_PROXY_CONFIG": str(path), "MCP_BASE_URL": "https://proxy.example/", "MCP_OAUTH_SECRET": "s",
                "USERS": f"marcel:{HASH}", **extra}
    return make


def test_minimal_users_config_loads(env):
    config = load_config(env(USERS))
    assert isinstance(config, Config)
    assert config.proxy.login.kind == "users"
    assert config.proxy.token_prefix == "mlpx_"
    assert config.proxy.store_salt == "mcp-login-proxy-oauth"
    assert config.base_url == "https://proxy.example"
    assert config.port == 8081


def test_env_reference_is_substituted(env):
    assert load_config(env(USERS)).proxy.login.users == f"marcel:{HASH}"


def test_unset_env_reference_is_an_error(env):
    e = env(USERS)
    del e["USERS"]
    with pytest.raises(ConfigError, match="USERS"):
        load_config(e)


def test_unknown_key_is_an_error(env):
    with pytest.raises(ConfigError, match="colour"):
        load_config(env(USERS + "colour: red\n"))


def test_two_login_kinds_is_an_error(env):
    with pytest.raises(ConfigError, match="exactly one"):
        load_config(env(USERS + "  upstream: {}\n"))


def test_no_login_kind_is_an_error(env):
    with pytest.raises(ConfigError, match="exactly one"):
        load_config(env(USERS.replace("  users: ${USERS}", "  {}")))


def test_static_tokens_with_users_is_an_error(env):
    with pytest.raises(ConfigError, match="static_tokens"):
        load_config(env(USERS + "static_tokens: token\n"))


def test_unknown_placeholder_is_an_error(env):
    with pytest.raises(ConfigError, match="nope"):
        load_config(env(USERS + 'upstream_headers: {Authorization: "{nope}"}\n'))


def test_users_mode_can_reference_only_the_user(env):
    with pytest.raises(ConfigError, match="password"):
        load_config(env(USERS + 'upstream_headers: {X-Pass: "{password}"}\n'))
    assert load_config(env(USERS + 'upstream_headers: {X-User: "{user}"}\n')).proxy.upstream_headers


def test_known_placeholders_are_accepted(env):
    yaml = USERS.replace("users: ${USERS}", "upstream: {}") + textwrap.dedent("""\
        vars: {basic: {base64: "{user}:{password}"}}
        upstream_headers: {Authorization: "Basic {basic}"}
        """)
    assert load_config(env(yaml)).proxy.upstream_headers == {"Authorization": "Basic {basic}"}


def test_users_must_be_argon2id(env):
    with pytest.raises(ConfigError, match="argon2id"):
        load_config(env(USERS, USERS="marcel:plaintext"))
    with pytest.raises(ConfigError, match="no users"):
        load_config(env(USERS, USERS=" "))


def test_parse_users_splits_on_whitespace():
    assert "," in HASH  # the hashes carry commas, so commas can't separate entries
    assert parse_users(f" marcel:{HASH}\nfabi:{HASH} ") == {"marcel": HASH, "fabi": HASH}
    assert parse_users(f"marcel:{HASH} fabi:{HASH}") == {"marcel": HASH, "fabi": HASH}


@pytest.mark.parametrize("name", ["MCP_BASE_URL", "MCP_OAUTH_SECRET"])
def test_missing_required_names_it(env, name):
    e = env(USERS)
    del e[name]
    with pytest.raises(ConfigError, match=name):
        load_config(e)


def test_missing_config_file_names_it(env, tmp_path):
    with pytest.raises(ConfigError, match="nothere.yaml"):
        load_config({**env(USERS), "MCP_PROXY_CONFIG": str(tmp_path / "nothere.yaml")})


def test_base_url_must_be_valid_issuer(env):
    with pytest.raises(ConfigError, match="MCP_BASE_URL"):
        load_config({**env(USERS), "MCP_BASE_URL": "http://x.example"})
    assert load_config({**env(USERS), "MCP_BASE_URL": "http://localhost:8081"}).base_url == "http://localhost:8081"


def test_port_must_be_int(env):
    with pytest.raises(ConfigError, match="MCP_PORT"):
        load_config({**env(USERS), "MCP_PORT": "eighty"})
    assert load_config({**env(USERS), "MCP_PORT": "9000"}).port == 9000
