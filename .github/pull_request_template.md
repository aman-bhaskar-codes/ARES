## What changed

Describe the smallest coherent change and the user/research failure it addresses.

## Verification

- [ ] focused tests added/updated
- [ ] `make test`
- [ ] `make eval-regression` when retrieval/routing/evidence behavior changes
- [ ] PostgreSQL/RLS/pgvector gates when persistence or tenancy changes
- [ ] frontend typecheck/test/build when UI contracts change
- [ ] OpenAPI regenerated when API contracts change
- [ ] no secrets, private documents, or fabricated benchmark claims

## Security / evidence impact

State whether the change affects auth, tenant isolation, SSRF, untrusted content, provider authority, citations, provenance, quotas, or stored user data. If none, say `none`.
