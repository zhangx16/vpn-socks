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


## SSH automation

The country selector reads the authenticated runner's live VPN Gate catalog, including candidate counts and update status. SSH jobs run on a separate authenticated HTTPS executor, survive browser closure, and return a verified VLESS link. Supported target installers: Alpine/OpenRC and Debian/Ubuntu/systemd. Existing Alpine deployment has been tested end to end.

Additional runtime secrets: `RUNNER_URL`, `RUNNER_TOKEN`, `CONTROL_HOSTS` (JSON array). The Worker hashes the trusted Sites identity into an opaque actor ID. The runner scopes task records to this actor, does not persist SSH credentials or per-job CF tokens, and marks in-flight work interrupted on executor restart.

SSH task polling, resume, node-link copying, singleton-country warnings and per-step progress are included. The frontend never places SSH credentials in localStorage.

```sh
bash scripts/build.sh
node --test scripts/test.mjs scripts/test-bridge.mjs
```

## Catalog refresh

The foreground page reloads the catalog every ten minutes and when it becomes visible. “获取最新候选” calls the owner-authenticated, same-origin POST `/api/regions/refresh`, which bypasses the executor's ten-minute cache. Successful results include the actual fetch timestamp and candidate counts. Failed forced refreshes preserve the previous catalog and report an error; listed candidates are not a guarantee of tunnel connectivity.
