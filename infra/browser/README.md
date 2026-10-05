# Browser sandbox profile

The optional M10 browser service is deliberately not runnable with an unverified, ad-hoc Chromium seccomp profile.

Vendor the exact profile that matches the pinned Playwright `v1.63.0` runtime:

```bash
python scripts/vendor_playwright_seccomp.py
python scripts/vendor_playwright_seccomp.py --check
```

The script downloads only the upstream `microsoft/playwright` file at the immutable `v1.63.0` tag and verifies its Git blob SHA (`fddc05fb520affb145404e6f6f647ca96af8087d`) before writing `infra/browser/seccomp_profile.json`.

The file is intentionally generated rather than silently substituted with `seccomp=unconfined`. If it is absent, the browser production overlay must not be enabled.
