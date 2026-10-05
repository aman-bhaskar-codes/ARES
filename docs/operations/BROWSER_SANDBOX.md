# M10 isolated browser fallback

ARES direct HTTP extraction remains the default. `BROWSER_ENABLED=true` only enables the research-worker client for a **separate browser renderer**; Chromium is never launched in the API or research worker.

## Security boundary

The sidecar is read-only and creates a fresh browser context for each render. It blocks non-HTTP(S) targets, URL credentials, non-standard ports, non-public DNS answers, non-GET/HEAD requests, downloads, service workers and WebSockets. Redirect/final URLs and every routed HTTP request are revalidated. The sidecar receives no database URL, Gemini key, OIDC secret, blob volume, Docker socket, host mounts, or user browser credentials.

Those checks are defense in depth, not a substitute for egress isolation. DNS validation followed by Chromium resolution has a rebinding/TOCTOU boundary that application code alone cannot close. **Do not enable the feature in production until the browser container has an enforced network policy/firewall that denies RFC1918, loopback, link-local, multicast, IPv6 ULA/link-local, cloud metadata and application/data networks for every browser-originated connection.** Playwright's own Docker guidance recommends a separate non-root user and Chromium sandbox/seccomp for untrusted crawling; do not run this service as root or add `--no-sandbox`.

## Build/run profile

Build `services/browser/Dockerfile` as a separate image. It pins Playwright 1.63.0 and runs as the image's `pwuser`. Before production promotion, pin the base image to an immutable digest, retain the Chromium-compatible seccomp profile, run with `no-new-privileges`, a read-only filesystem and bounded `/tmp`, and verify the egress firewall with SSRF fixtures. Keep one active render initially.

The browser client is deliberately disabled by default. If the renderer is unavailable or blocked, ARES preserves normal Safe HTTP extraction and returns partial research rather than granting broader browser authority.

## Release activation checklist

Vendor and verify the exact seccomp profile on a networked release machine:

```bash
python scripts/vendor_playwright_seccomp.py
python scripts/vendor_playwright_seccomp.py --check
```

Then use the browser overlay in addition to the normal production Compose file only after the external egress policy has been installed and tested:

```bash
docker compose \
  -f infra/production/compose.yaml \
  -f infra/production/compose.browser.yaml \
  config

docker compose \
  -f infra/production/compose.yaml \
  -f infra/production/compose.browser.yaml \
  up -d
```

The overlay intentionally exposes no browser host port. The worker reaches it only on the internal `browser-control` network. The browser has a separate egress network and must be constrained by the deployment platform/host firewall. A Compose network name is **not** by itself an egress firewall.

Before enabling live traffic, verify at minimum that direct navigation, redirects, subresources, DNS rebinding attempts, IPv4/IPv6 private ranges, link-local addresses and the cloud metadata endpoint are denied from the browser container while ordinary public HTTPS pages remain readable. Retain the test output with the release evidence.
