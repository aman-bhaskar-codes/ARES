# Security policy

ARES Milestone 6 includes a public-product security boundary (OIDC sessions, CSRF, workspace roles, PostgreSQL RLS, SSRF controls, bounded uploads/jobs and hardened production containers), but a source release is **not** a claim of independent penetration testing or production safety on every deployment platform.

Please report suspected vulnerabilities privately through **GitHub Private Vulnerability Reporting** when the repository enables it. If that channel is unavailable, contact the repository owner through a private channel before publishing exploit details.

High-priority reports include authentication/session bypass, CSRF, cross-workspace/IDOR or RLS bypass, API/worker database-role confusion, SSRF/DNS-rebinding bypass, credential/provider-token exposure, unsafe file parsing, prompt-injection-to-tool escalation, stale-lease result acceptance, or cross-tenant evidence/artifact access.

Do not include real provider credentials, private research documents, session cookies or unredacted personal data in a public issue.
