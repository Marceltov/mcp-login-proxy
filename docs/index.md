---
hide:
  - toc
---

<div class="tm-hero" markdown>

# One login page for any MCP server

<p class="tm-hero__lead">mcp-login-proxy puts an OAuth login in front of an MCP server, so claude.ai, the Claude apps, Claude Code and any other MCP client can connect by URL and sign in once on a form. Requests then pass through to the server unchanged. Everything about the server behind it is one config file.</p>

[Set it up](getting-started.md){ .md-button .md-button--primary } [Configuration](configuration.md){ .md-button }

</div>

## What it is for

Many MCP servers either take a credential on every request (an API token, `Basic user:token`, a session token from a login call) or have no login at all. MCP clients like claude.ai can't send such headers; they expect OAuth. The proxy is that OAuth login:

- **A login, checked the way the server needs.** The config file chooses one of four checks:
    - **`users`**: a fixed list of users and argon2id password hashes, for a server with no login of its own.
    - **`upstream`**: the form's values are tried with one request to the server, for one that takes a credential per request.
    - **`exchange`**: the form is sent to a login URL and a field of the answer becomes the token, for one that hands out tokens on login (Trilium Notes, for example).
    - **`oidc`**: people sign in at an OpenID Connect provider such as Authentik instead of a form, and the proxy lets in the groups or users you allow.
- **The server's own tools, unchanged.** Every `/mcp` request goes to the server as it is. The proxy only adds the headers the config file names, rendered from that login. New tools from a server update appear without a proxy release.
- **Credentials stay on your side.** The login page is the proxy's own; the MCP client only ever holds opaque OAuth tokens that mean nothing elsewhere. See [Security](security.md).
- **House rules.** With `instructions` set, every client gets your standing instructions when it connects.

## Examples

Ready-made config files are in [`docs/examples`](https://github.com/Marceltov/mcp-login-proxy/tree/main/docs/examples): Trilium Notes' built-in MCP server, OpenCloud's MCP server, OpenBB's MCP server, and any MCP server signed in through Authentik.

## History

The proxy started as trilium-mcp-proxy, an OAuth front for Trilium Notes only, and became general in v0.2.0 ([ADR 0003](https://github.com/Marceltov/mcp-login-proxy/blob/main/docs/adr/0003-a-general-login-front-configured-per-deployment.md)). A Trilium deployment of trilium-mcp-proxy moves over with the Trilium example config, and its existing logins keep working.
