"""The example configs from docs/examples, loaded the way a deployment loads them."""

from pathlib import Path

from argon2 import PasswordHasher

from mcp_login_proxy.config import ProxyConfig, load_proxy_config

EXAMPLES = Path(__file__).parent.parent / "docs" / "examples"

PASSWORDS = {"marcel": "marcel-pw", "fabi": "fabi-pw"}
_HASHER = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)  # fast for tests, still argon2id
USERS = " ".join(f"{name}:{_HASHER.hash(pw)}" for name, pw in PASSWORDS.items())


def example(name: str, **env: str) -> ProxyConfig:
    return load_proxy_config(EXAMPLES / f"{name}.yaml", env)


def trilium(url: str) -> ProxyConfig:
    return example("trilium", TRILIUM_URL=url)


def openbb(url: str) -> ProxyConfig:
    return example("openbb", OPENBB_MCP_URL=f"{url}/mcp", OPENBB_MCP_USERS=USERS)


def opencloud(url: str) -> ProxyConfig:
    return example("opencloud", OPENCLOUD_MCP_URL=f"{url}/mcp")
