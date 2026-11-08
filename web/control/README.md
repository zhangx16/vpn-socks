# VPN Socks Control

Owner-private Cloudflare task console. It configures a node's proxied A record, per-host Origin Rule port and TLS Configuration Rule, then checks the WebSocket handshake. Existing server deployment and throughput failover are provided by the parent vpn-socks project.

## Runtime

- `CF_API_TOKEN`: secret. Zone Read, DNS Edit, Origin Rules Edit, Config Rules Edit.
- `NODE_PRESETS`: secret JSON array of `{name, region, domain, ip, port, path}`. No presets or credentials are embedded in source.
- Hosted authentication is enforced by Sites; API operations also require the platform identity header and same-origin POST requests.

## Build and tests

```sh
node --test scripts/test.mjs
bash scripts/build.sh
node scripts/validate-artifact.mjs
```

The build embeds the HTML and API handlers into one Cloudflare Worker ES module at `dist/server/index.js`. Tokens remain in runtime secrets or transient task memory. Browser history contains task summaries only. CF API failures trigger best-effort rollback of completed writes; DNS propagation or handshake failure is reported as pending rather than falsely declaring the node verified.

Publication uses the Sites source and artifact workflow. The Site remains private to its owner. Never commit `.env`, credentials, runtime reports or local live-test scripts.
