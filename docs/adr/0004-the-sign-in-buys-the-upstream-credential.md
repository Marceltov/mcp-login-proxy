---
status: accepted
date: 2026-11-19
decision-makers: Marcel Bruckner
---

# The sign-in buys the upstream's credential

## Context and Problem Statement

opencloud-mcp takes `Basic <user>:<app token>` on every request, so with `login.upstream` everyone first makes an OpenCloud app token and pastes it into the form. OpenCloud's own login is Authentik; its other way to connect claude.ai (opencloud-mcp's MCP authorization) needs RFC 8693 token exchange at the provider, which Authentik does only through a patched fork and two federated providers, and which Authelia doesn't offer. In the homelab that route also left claude.ai without a refresh token, so the connector needed a new login every hour (MarcelBruckner-Homelab/homelab#446).

Can people sign in at Authentik once and have the proxy make the app token?

## Considered Options

* **`login.oidc.credential`:** after the sign-in, one request with the provider's access token whose answer holds the credential (OpenCloud: `POST /auth-app/tokens`).
* **Keep `login.upstream`:** works with any provider, but everyone handles a token.
* **Admin impersonation** (`AUTH_APP_ENABLE_IMPERSONATION`, `userName=`): the proxy would hold an admin's power over every account.

## Decision Outcome

Chosen: **`login.oidc.credential`**, v0.4.0, on mcp-login-oauth v0.5.0's `OidcLogin(pass_access_token=True)` (its ADR 0005), switched on only when `credential` is configured. The request may use `{access_token}` and `{user}` and nothing else (checked at load). The grant keeps `{user}` and the credential; the access token is used for this request and dropped. Only someone who passed the allow list gets a credential made; a refusal or an answer without the field shows on the login page.

### Consequences

* Good, because one sign-in at the provider, with its MFA and passkeys, gives the client a working connector, and the client's own refresh token keeps it working (mcp-login-oauth rotates it for 30 days after each use).
* Good, because only an ordinary authorization-code client is needed at the provider: no token exchange, no federation, and it works the same with Authelia.
* Neutral, because the credential's expiry ends the login: OpenCloud's app tokens carry one, chosen in the request (`expiry=`), and a new sign-in makes a new one.
* Bad, because each sign-in leaves one more app token at OpenCloud until it expires; disconnecting doesn't delete it (OpenCloud deletes by the token's id, which the create answer doesn't return).
