# Security policy

Production requires OIDC authentication, HTTPS, secure cookies, distinct API and worker database roles, migrated PostgreSQL and private blob storage. Local authentication-disabled mode is for development only.

Report vulnerabilities through GitHub private vulnerability reporting for `aman-bhaskar-codes/ARES` when available. If that channel is unavailable, open an issue asking for a private reporting contact without including exploit details, tokens, personal data or vulnerable deployment addresses. Do not publish an exploit while arranging private disclosure.

Include the affected revision, a minimal reproduction, impact and suggested mitigation. Never include real credentials or another workspace's data. The maintainers should acknowledge reports, assess severity and coordinate fixes and disclosure; no response-time guarantee is currently published.

Security checks in CI cover configuration, authorization, SSRF and input regression cases. They supplement review and monitoring; they do not establish a complete security guarantee.
