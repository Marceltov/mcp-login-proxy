# Connect a client

Every client gets the same URL, the proxy's `MCP_BASE_URL` plus `/mcp`, for example `https://mcp.example.org/mcp`. The first time, the client opens the proxy's login page in your browser. After that the client refreshes its tokens on its own.

=== "claude.ai and the Claude apps"

    1. *Customize → Connectors → Add custom connector*.
    2. A name and the URL. Keep the detected OAuth settings.
    3. Sign in on the page that opens.
    4. In a chat, switch the connector on under **+ → Connectors**.

    A connector added on claude.ai is also available in the Claude desktop and mobile apps.

=== "Claude Code"

    ```bash
    claude mcp add --transport http my-server https://mcp.example.org/mcp -s user
    ```

    Restart Claude Code, run `/mcp`, pick the server and choose **Authenticate**. A browser opens on the proxy's login page.

=== "Other MCP clients"

    Add the URL as a streamable HTTP server. Any client that supports MCP's OAuth flow finds the login on its own through the proxy's `/.well-known/oauth-protected-resource` and `/.well-known/oauth-authorization-server` metadata.

## With a token instead

Where the config file sets `static_tokens`, a client can send the server's own token instead of logging in:

```bash
claude mcp add --transport http trilium https://trilium-mcp.example.org/mcp \
  -H "Authorization: Bearer <token>" -s user
```

The proxy passes it on, with or without `Bearer`, and the server checks it.

## Disconnect a client

Remove the connector or server in the client, which revokes the login (and calls the config file's `revoke` request, if there is one). Changing `MCP_OAUTH_SECRET` logs every client out at once.
