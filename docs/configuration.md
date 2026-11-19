# Configuration

## Environment

| Variable | Default | Meaning |
|---|---|---|
| `MCP_BASE_URL` | required | Public URL of the proxy; also the OAuth issuer (`https`, or `http` only for localhost) |
| `MCP_OAUTH_SECRET` | required | Encrypts the stored logins in `/data`; changing it logs every client out |
| `MCP_PROXY_CONFIG` | `/config/proxy.yaml` | The config file |
| `MCP_PORT` | `8081` | Port the proxy listens on inside the container |
| `LOG_LEVEL` | `INFO` | Python log level |
| any other | | Referenced from the config file as `${NAME}`, for secrets such as the user list |

A missing or invalid setting stops the container at startup with a message naming it.

## The config file

`${NAME}` is replaced from the environment when the file is loaded; a name that isn't set is an error. `{name}` placeholders are filled per login or per request from the variables below. `{{` and `}}` are literal braces.

| Key | Default | Meaning |
|---|---|---|
| `service_name` | required | Shown on the login form |
| `upstream` | required | The MCP server's full URL, e.g. `http://trilium:8080/mcp`; the query string of each request is kept |
| `instructions` | none | Added to the server's `initialize` result as `instructions` |
| `fields` | required, none with `oidc` | The login form: a list of `{name, label, type, required, autocomplete, hint}`; `type` is `text`, `password` or `email` |
| `login` | required | Exactly one of `users`, `upstream`, `exchange` or `oidc` (below) |
| `messages` | none | For `exchange`: an error code from the login answer → the text shown on the form |
| `revoke` | none | A request sent when a client revokes its login: `{method, url, headers, json}` |
| `static_tokens` | off | A variable name: a raw `Authorization` header (with or without `Bearer`) is accepted as that variable and passed on; the server judges it. Not allowed with `users` |
| `vars` | none | Derived variables: `{name: {base64: "<template>"}}` |
| `upstream_headers` | none | Headers added to each forwarded request, e.g. `{Authorization: "Basic {basic}"}`. The client's own `Authorization` is never forwarded |
| `health` | none | A URL `/health` checks; without it `/health` only says the proxy runs |
| `token_prefix` | `mlpx_` | Prefix of the proxy's OAuth tokens |
| `store_salt` | `mcp-login-proxy-oauth` | Salt for the store's encryption key |

Text fields are trimmed before they're used; password fields are passed exactly as typed.

### `login.users`

A fixed list: `name:hash` entries separated by spaces or newlines, the hashes argon2id (`mcp-login-proxy hash` makes one). The form must have a `user` and a `password` field. The login only keeps `{user}`, never the password, and `static_tokens` is refused: the server behind it has no login, so a raw token would let anyone in.

### `login.upstream`

`upstream: {}`. The form's values are rendered into `upstream_headers` and tried with one `initialize` request to `upstream`; any 2xx answer accepts the login. The login keeps the form's values that `upstream_headers`, `vars` and `revoke` use.

### `login.exchange`

| Key | Meaning |
|---|---|
| `request` | `{method, url, headers, json}` with the form's fields as placeholders. In `json`, a value that renders empty is left out |
| `token` | The JSON field of the answer that holds the token |
| `variable` | The variable it becomes, default `token` |
| `error` | The JSON field of a refusal, looked up in `messages`; otherwise the form shows the HTTP status |

### `login.oidc`

People sign in at an OpenID Connect provider (Authentik, Keycloak, …) instead of a form: the login page shows the consent card and one button, "Continue with <name>". mcp-login-oauth does the round trip and checks the ID token; the proxy then lets in whoever is allowed. Example: [`docs/examples/authentik.yaml`](https://github.com/Marceltov/mcp-login-proxy/blob/main/docs/examples/authentik.yaml).

| Key | Default | Meaning |
|---|---|---|
| `issuer` | required | The provider's issuer, exactly as published. Authentik: `https://<host>/application/o/<slug>/` |
| `client_id`, `client_secret` | required, none | The client registered at the provider; without a secret it is public (PKCE only) |
| `name` | `single sign-on` | On the button and in error pages |
| `scopes` | `[openid, profile, email]` | Authentik puts `groups` into `profile` |
| `user_claim` | `preferred_username` | The claim that becomes `{user}` |
| `allowed_groups`, `allowed_users` | none | Who gets in: a name in `allowed_users` or one of the token's `groups` in `allowed_groups`. At least one list is required: an account at the provider alone is not enough |
| `verify_tls` | `true` | `false` turns certificate checks off for the provider |

Register `<MCP_BASE_URL>/login/callback` as the redirect URI at the provider. The login keeps only `{user}`; `fields` and `static_tokens` are refused with `oidc`. `{user}` can go upstream, for example `upstream_headers: {X-Forwarded-User: "{user}"}`.

In Authentik: *Applications → Providers → Create → OAuth2/OpenID Provider*, then an application for it. Checked against Authentik 2026.8:

- client type **confidential**, the redirect URI above (strict), a signing key;
- the scope mappings **openid, profile and email** (`groups` comes with `profile`); without them the token carries no scopes and the userinfo endpoint answers 403;
- grant types including **authorization_code**: a provider made through the API or a blueprint starts with none, and Authentik then refuses the login as "otherwise malformed";
- profile claims don't have to be in the ID token: the proxy reads `preferred_username` and `groups` from the userinfo endpoint.

A policy binding on the application can limit who may sign in there as well.

## Data volume

Mount a volume at `/data`. It holds the OAuth store (registered clients, tokens and each login's variables), encrypted with a key derived from `MCP_OAUTH_SECRET` and `store_salt`. Without the volume, every container restart logs all clients out.

## Endpoints

| Path | What |
|---|---|
| `/mcp` | The MCP server, behind the login |
| `/health` | `{"status": "ok"}`, plus `"upstream": "ok" \| "unreachable"` with `health` set; no login needed |
| `/.well-known/…`, `/authorize`, `/token`, `/register`, `/revoke` and the login page | The OAuth endpoints MCP clients find and use on their own |

## Moving from trilium-mcp-proxy

Mount [`docs/examples/trilium.yaml`](https://github.com/Marceltov/mcp-login-proxy/blob/main/docs/examples/trilium.yaml) with `TRILIUM_URL` set, move `MCP_INSTRUCTIONS` into `instructions`, keep `MCP_BASE_URL`, `MCP_OAUTH_SECRET` and the `/data` volume. Its `token_prefix`, `store_salt` and `variable` are trilium-mcp-proxy's, so every existing login keeps working.
