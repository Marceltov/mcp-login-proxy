# mcp-login-proxy

<p>
  <a href="https://mcp-login-proxy.marceltov.de/">
    <img alt="Documentation" src="https://img.shields.io/badge/docs-mcp--login--proxy.marceltov.de-2f7a27">
  </a>
  <a href="https://github.com/Marceltov/mcp-login-proxy/pkgs/container/mcp-login-proxy">
    <img alt="GHCR image" src="https://img.shields.io/github/v/release/Marceltov/mcp-login-proxy?logo=docker&logoColor=white&label=ghcr.io%2Fmarceltov%2Fmcp-login-proxy&color=2496ED">
  </a>
  <a href="LICENSE">
    <img alt="License: AGPL v3" src="https://img.shields.io/badge/License-AGPL_v3-blue.svg">
  </a>
</p>

An OAuth login front for MCP servers. Add its URL to claude.ai, the Claude apps, Claude Code or any other MCP client, sign in once on a form, and every request goes to the MCP server behind it unchanged. Everything about that server is one config file:

- **How a login is checked:** against a fixed list of users and argon2id hashes (`users`, for a server with no login of its own), with one request to the server (`upstream`, for one that takes a credential per request), or at a login URL whose answer holds a token (`exchange`, for one that hands out tokens).
- **What is added to each request:** headers rendered from that login, e.g. `Authorization: Basic {basic}`. The client's own `Authorization` is never forwarded.
- **House rules:** `instructions` are added to the server's `initialize` answer.

Example configs: [Trilium Notes](docs/examples/trilium.yaml), [OpenCloud](docs/examples/opencloud.yaml), [OpenBB](docs/examples/openbb.yaml). The login comes from [mcp-login-oauth](https://github.com/Marceltov/mcp-login-oauth). This project was trilium-mcp-proxy until v0.2.0 ([ADR 0003](docs/adr/0003-a-general-login-front-configured-per-deployment.md)).

## Documentation

**Full documentation: [mcp-login-proxy.marceltov.de](https://mcp-login-proxy.marceltov.de/)**

- [Quick start](https://mcp-login-proxy.marceltov.de/getting-started/): write the config file, add the proxy, publish it over HTTPS
- [Configuration](https://mcp-login-proxy.marceltov.de/configuration/): every key, and moving from trilium-mcp-proxy
- [Connect a client](https://mcp-login-proxy.marceltov.de/connecting/), [security](https://mcp-login-proxy.marceltov.de/security/) and [how it works](https://mcp-login-proxy.marceltov.de/how-it-works/)

## Run it

```yaml
services:
  mcp-proxy:
    image: ghcr.io/marceltov/mcp-login-proxy:0.2.0
    restart: unless-stopped
    environment:
      MCP_BASE_URL: https://mcp.example.org   # the public URL, behind your TLS proxy
      MCP_OAUTH_SECRET: ${MCP_OAUTH_SECRET}   # openssl rand -hex 32
    volumes:
      - ./proxy.yaml:/config/proxy.yaml:ro
      - mcp-proxy-oauth:/data
    ports:
      - "8081:8081"

volumes:
  mcp-proxy-oauth:
```

`docker run --rm -it ghcr.io/marceltov/mcp-login-proxy hash` makes a password hash for `login.users`.

## Development

```bash
uv sync
uv run pytest -q --ignore=tests/live   # unit tests, against fake upstreams
./run-tests.sh -q                     # unit + live, against a disposable Trilium (Docker), with the Trilium example config
```

## License

Copyright © 2026 Marcel Bruckner.

Licensed under the [GNU Affero General Public License v3.0 or later](LICENSE) (AGPL-3.0-or-later). You may use, modify, and redistribute it, but any modified version — **including one you run as a network service** — must be released under the same license with its source made available to its users, and the original copyright notice preserved. See [LICENSE](LICENSE) for the full terms.
