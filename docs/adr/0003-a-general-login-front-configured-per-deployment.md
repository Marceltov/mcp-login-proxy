---
status: accepted
date: 2026-11-19
decision-makers: Marcel Bruckner
---

# A general login front, configured per deployment

## Context and Problem Statement

trilium-mcp-proxy put an OAuth login in front of Trilium's built-in MCP server ([ADR 0001](0001-transparent-oauth-proxy-for-trilium-mcp.md)). Other MCP servers have the same need: opencloud-mcp takes `Basic user:app token` on every request (#10), and OpenBB's MCP server, which the homelab wants to reach from claude.ai, has no login at all (MarcelBruckner-Homelab/homelab#545). How does one proxy serve all of them?

## Considered Options

* **Named modes in code** (`PROXY_MODE=trilium|users`, later `opencloud`): the smallest change, but every new server needs a release.
* **Configuration, with Trilium's login as one built-in check:** half general; the next server that hands out tokens on login needs code again.
* **Everything in one config file:** the form, the login check (a user list, one request to the server, or a login exchange), revoke, raw tokens and the headers added upstream.

## Decision Outcome

Chosen: **everything in one config file** (Marcel: "why do we have to hardcode Trilium?"). The code names no service; Trilium, OpenCloud and OpenBB are files in `docs/examples`, and the tests run against all three.

The repository moved with the change: trilium-mcp-proxy's history continues here as **mcp-login-proxy**, from v0.2.0, and trilium-mcp-proxy is archived with a pointer, as trilium-mcp was before it.

### Consequences

* Good: a new MCP server is a config file; no release.
* Good: Trilium deployments move without logging anyone out. The Trilium example keeps trilium-mcp-proxy's token prefix (`tmpx_`), store salt and grant variable (`etapi_token`); a test mints a token with the old settings and uses it on the new app.
* Good: the `users` check is safe by construction: argon2id only, a dummy hash for unknown names, the grant holds only the user name, and raw tokens are refused at startup.
* Bad: more configuration surface. A mistake shows at startup (unknown keys and placeholders are errors), not at the first login.
* Bad: Trilium's friendly login messages now live in the config file (`messages`); without them the form shows the HTTP status.
* Neutral: the image name changed to `ghcr.io/marceltov/mcp-login-proxy`; the old images stay on GHCR.
