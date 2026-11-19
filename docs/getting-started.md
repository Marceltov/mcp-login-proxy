# Quick start

You need the MCP server you want to put behind a login, Docker Compose, and a reverse proxy that serves HTTPS (Caddy, Traefik, nginx, Cloudflare Tunnel, …).

## 1. Write the config file

Start from the [example](https://github.com/Marceltov/mcp-login-proxy/tree/main/docs/examples) closest to your server and save it as `proxy.yaml` next to your compose file. For a server without a login of its own, that's the users example:

```yaml
service_name: OpenBB
upstream: http://openbb-mcp:8001/mcp
fields:
  - {name: user, label: User name, autocomplete: username, required: true}
  - {name: password, label: Password, type: password, required: true}
login:
  users: ${MCP_USERS}
```

For each user, make a hash (the password is read twice, without echo):

```bash
docker run --rm -it ghcr.io/marceltov/mcp-login-proxy hash
```

Every key is explained under [Configuration](configuration.md).

## 2. Add the proxy next to the server

```yaml
services:
  mcp-proxy:
    image: ghcr.io/marceltov/mcp-login-proxy:0.2.0
    restart: unless-stopped
    environment:
      MCP_BASE_URL: https://mcp.example.org   # the public URL, behind your TLS proxy
      MCP_OAUTH_SECRET: ${MCP_OAUTH_SECRET}   # openssl rand -hex 32
      MCP_USERS: ${MCP_USERS}
    volumes:
      - ./proxy.yaml:/config/proxy.yaml:ro
      - mcp-proxy-oauth:/data
    ports:
      - "8081:8081"

volumes:
  mcp-proxy-oauth:
```

Put the secrets in a `.env` file next to the compose file. **Single-quote the user list:** Compose replaces `$` in `.env` values, and argon2 hashes are full of them.

```bash
echo "MCP_OAUTH_SECRET=$(openssl rand -hex 32)" >> .env
echo "MCP_USERS='alice:\$argon2id\$v=19\$… bob:\$argon2id\$v=19\$…'" >> .env
docker compose up -d mcp-proxy
```

## 3. Publish it over HTTPS

Point your reverse proxy at port 8081 under the hostname in `MCP_BASE_URL`. With Caddy:

```
mcp.example.org {
    reverse_proxy localhost:8081
}
```

`MCP_BASE_URL` must match the public URL exactly: it's the OAuth issuer, and clients compare it byte for byte. Plain `http` is only accepted for `localhost`.

Check it:

```bash
curl https://mcp.example.org/health
# {"status": "ok"}
curl -i -X POST https://mcp.example.org/mcp
# HTTP/2 401
```

## 4. Connect a client

Add `https://mcp.example.org/mcp` to your client and log in. See [Connect a client](connecting.md).
