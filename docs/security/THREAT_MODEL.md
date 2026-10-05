# ARES threat model — through Milestone 06

## Trust boundaries

Browser/API callers, identity providers, database roles, worker processes and external research providers are separate trust boundaries. Every web page, search result, scholarly abstract/metadata record, README, uploaded document and extracted PDF passage is untrusted content data rather than privileged instruction. Gemini/database/provider credentials exist only server-side. The synthesis model has no network, shell, filesystem or database tool authority.

## Identity and session boundary

- production authentication uses OpenID Connect Authorization Code + PKCE S256;
- state and nonce are one-time, expiring and server-persisted;
- callback return targets must remain same-origin relative paths and reject slash/backslash/control-character tricks;
- discovery cannot downgrade an HTTPS issuer to HTTP token/JWKS/UserInfo endpoints;
- ID Tokens are cryptographically verified against provider JWKS and checked for issuer, audience, `azp` when required, `exp`, `nbf`, bounded future `iat`, nonce and subject shape;
- optional UserInfo `sub` must equal the validated ID Token `sub`;
- provider access tokens are never persisted;
- browser sessions use opaque random tokens; only hashes are stored server-side;
- mutation requests require an independent CSRF token plus same-origin checks;
- logout revokes the server-side session;
- viewer-role principals cannot mutate research resources.

## Tenant / database isolation

- conversations, runs, documents, audit events and derived research rows are workspace-owned;
- PostgreSQL uses `FORCE ROW LEVEL SECURITY` for research-bearing tables;
- each API transaction sets `app.workspace_id` and `app.user_id` locally; when no principal exists the values are explicitly blanked so pooled connections cannot inherit the previous tenant;
- API and worker privileges are separated: API is `NOBYPASSRLS`; only the durable cross-workspace worker role is intentionally `BYPASSRLS`;
- the fleet-wide active-run total is exposed through one narrowly scoped `SECURITY DEFINER` aggregate rather than broad cross-tenant API access;
- per-user/workspace admission remains ordinary tenant-scoped querying;
- audit metadata is bounded and not an arbitrary credential/data sink.

## Retrieval / SSRF

- only public HTTP(S) URLs;
- URL userinfo, control characters and non-standard ports rejected;
- DNS answers must **all** be globally routable, including IPv4/IPv6; loopback/private/link-local/metadata destinations are blocked;
- HTTP connection pinned to the validated resolved IP to reduce DNS-rebinding risk;
- every redirect destination is revalidated;
- response bytes, content types, redirect count, per-run concurrency and process concurrency are bounded.

## Prompt injection / untrusted content

- privileged synthesis rules are a separate Gemini `system_instruction`;
- user question/evidence are serialized as a data envelope;
- synthesis interactions use `store=False` and expose no model-side tools;
- evidence IDs are server-created and claims can cite only evidence belonging to the run;
- remote-content risk scanning records bounded categories for visibility/evaluation but never changes authorization or source trust;
- instruction-like source content remains evidence data.

## Jobs, quotas and overload

- idempotent run creation;
- PostgreSQL-serialized global/workspace/user active-run admission;
- retryable HTTP 429 with `Retry-After` when capacity is full;
- durable leases and lease-token fencing;
- bounded retries and fail-closed retry exhaustion;
- cancellation persisted and checked by workers;
- serialized provider/model quota reservations;
- strict-free mode refuses paid fallback and Jev activation.

## Documents / provenance

- upload/request-body, PDF byte/page and parser-time limits;
- PDF parsing in a bounded subprocess;
- explicit `needs_ocr` instead of claiming image-only PDFs were parsed;
- content-addressed blobs and immutable hashes;
- reusable document IDs separated from run-scoped source IDs;
- page-aware evidence locators and immutable document versions;
- failed document persistence removes newly written bytes only when not referenced elsewhere.

## Public edge and browser

- production requires HTTPS public origin and same browser/API origin;
- Trusted Host checks the configured host;
- HSTS, CSP, no-sniff, frame denial, restrictive referrer/permissions/cross-origin policies are emitted in production;
- authentication responses are `no-store`;
- mutation body size is bounded before application parsing;
- expensive authenticated research admission is database-backed; anonymous volumetric rate limiting remains a reverse-proxy/CDN/WAF responsibility rather than a misleading in-process distributed limiter.

## Process / deployment boundary

- production images run non-root with read-only root filesystems, dropped Linux capabilities and `no-new-privileges`;
- PostgreSQL remains on an internal-only data network; API/worker/SearXNG have a separate egress network for live provider access;
- worker shutdown marks the instance draining before stopping new durable-job claims;
- readiness and liveness are distinct; production readiness can require correct schema revision and an active worker;
- telemetry/exporter failure is not allowed to own research correctness.

## Important limitations and external evidence gates

The prompt-injection risk scanner is not a firewall. Source grouping does not prove editorial independence. Development regression fixtures are not an external benchmark. Source-complete controls are not proof of production uptime or independent security review.

Before an internet-facing production launch, operators must still run the PostgreSQL/RLS integration suite on the target database roles, build/run the production containers, exercise real OIDC/provider flows, configure an edge rate/abuse-control layer and secret management, perform backup/restore and rollout drills, and obtain an independent penetration/security review appropriate to the deployment.

## M11 visual artifact and export boundary

M11 visualizations are untrusted-data renderings over trusted ARES schemas, not executable model output. The backend revalidates every dataset and same-run lineage reference before persistence. Chart/graph libraries receive approved bounded data only; model-provided JavaScript, HTML, data URLs, SQL, Python and arbitrary formulas are not accepted. Numeric chart rows originate only from finite normalized table cells that were also promoted to run evidence, with unit compatibility enforced before publication.

Visualization tables carry direct `workspace_id`, PostgreSQL RLS/FORCE RLS policies, and the API role receives SELECT-only grants. Server CSV export re-enters the run/workspace authorization boundary, emits `private, no-store`, retains source/evidence identifiers and escapes spreadsheet formula prefixes. The graph is capped to a bounded neighborhood so malicious or accidental corpus size cannot force an unbounded browser graph.

The React rich-text path intentionally does not enable raw HTML. CSP remains defense in depth; libraries that require inline style attributes do not receive script execution authority. Static SPA fallback is limited to non-API routes: `/api/*` must never resolve to `index.html`.
