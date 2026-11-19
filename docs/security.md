# Security

## Where credentials go

Only to your own servers. The login page is served by the proxy:

1. The MCP client (say claude.ai) sends your browser to the proxy's `/authorize` page.
2. You fill in the form there. The browser posts it to the proxy, over your HTTPS.
3. The proxy checks it the way the config file says: against the user list (`users`), with one request to the server (`upstream`), or at the server's login URL (`exchange`). Nothing from the form is logged.
4. The client receives an authorization code and trades it for opaque OAuth tokens. Those tokens mean nothing outside your proxy.

The MCP client never sees what was typed into the form, and never sees the credential the proxy sends upstream.

## What is stored

In `/data`, encrypted with a key derived from `MCP_OAUTH_SECRET` and `store_salt`: the registered clients, and for each login its OAuth tokens and the variables the forwarded requests need.

| Check | A login keeps |
|---|---|
| `users` | the user name only |
| `upstream` | the form values the upstream headers use (for example a user name and an app token) |
| `exchange` | the token from the login answer, plus form values the headers use |

Anyone with the volume *and* the secret could use what is stored, so keep `MCP_OAUTH_SECRET` out of the compose file (use `.env`) and treat the volume like the server's own data.

## A server without a login

With `users`, the proxy is the only gate in front of the server, so:

- passwords are argon2id hashes, never plain text, and the config refuses anything else;
- an unknown user name is checked against a dummy hash, so it takes as long as a wrong password and doesn't reveal which names exist; both get the same message;
- raw tokens are refused (`static_tokens` can't be set), so only a token the proxy issued gets through;
- the server's own port must not be reachable from where the proxy is published: the proxy protects its URL, not the server's.

## Failed logins

A refused login is answered after a short delay, which slows down guessing.

## What the proxy can't protect

A client that is logged in has whatever access the server gives that credential. Only connect clients you trust, and remove the ones you no longer use.
