# Security Policy

ARES is designed for high-assurance research and engineering workloads. We take security vulnerabilities seriously and adhere to coordinated disclosure practices.

---

## Supported Versions

Only the latest active development branch and release tags receive security fixes:

| Version | Supported |
|---------|-----------|
| `0.12.x` (v3 / current) | :white_check_mark: Yes |
| `< 0.12.0` | :x: No |

---

## Security Architecture & Deployment Guarantees

- **Production Security Invariants**: Production deployments require `AUTH_MODE=oidc`, TLS/HTTPS endpoints, secure session cookies (`SESSION_COOKIE_SECURE=true`), distinct database credentials for API and background workers, and private object/blob storage.
- **Local Isolation**: `AUTH_MODE=disabled` is strictly constrained to local loopback addresses (`127.0.0.1`, `localhost`, `::1`). Remote exposure without authentication requires explicit opt-in via `ALLOW_INSECURE_REMOTE_DISABLED_AUTH=true`.
- **Egress & SSRF Protection**: All outbound network requests to search providers, scholarly archives, and external sources pass through strict URL validation, DNS rebinding guards, private-subnet blocks, and bounded timeouts.
- **Data Isolation**: Database interactions enforce Row-Level Security (RLS) on PostgreSQL, preventing cross-tenant or cross-workspace data leakage.
- **Static Assets & Downloads**: All download endpoints enforce RFC 6266 filename sanitization and security response headers (`X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, strict CSP).

---

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

1. **GitHub Advisory (Preferred)**: Submit a report via [GitHub Private Vulnerability Reporting](https://github.com/aman-bhaskar-codes/ARES/security/advisories/new) if enabled on the repository.
2. **Private Disclosure Request**: If GitHub Advisories are not accessible, open a public issue requesting a private security contact, omitting all exploit details, tokens, personal data, or vulnerable endpoints.

### What to Include

To help us investigate and remediate quickly, please include:
- Affected commit SHA or release version.
- Step-by-step reproduction instructions or proof-of-concept (POC).
- Potential impact and severity assessment.
- Suggested mitigations (if known).

### Responsible Disclosure

- Allow the maintainers reasonable time to investigate, reproduce, and resolve the issue before publishing any details.
- Never access, download, or modify user or workspace data belonging to others.
