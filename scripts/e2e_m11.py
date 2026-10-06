from __future__ import annotations

import argparse
import os
from urllib.parse import quote


def required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"{name} is required for the M11 browser gate")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="M11 browser/accessibility smoke over a running ARES instance"
    )
    parser.add_argument("--browser", choices=["chromium", "firefox", "webkit"], default="chromium")
    parser.add_argument(
        "--base-url", default=os.getenv("ARES_E2E_BASE_URL", "http://127.0.0.1:8000")
    )
    parser.add_argument(
        "--min-activity-events",
        type=int,
        default=200,
        help="minimum persisted events required by the release replay fixture",
    )
    args = parser.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit(
            "playwright is required; run this gate in the browser-test profile"
        ) from exc

    conversation = required("ARES_E2E_CONVERSATION_ID")
    run = required("ARES_E2E_RUN_ID")
    evidence = required("ARES_E2E_EVIDENCE_ID")
    deep_link = (
        f"{args.base_url.rstrip('/')}/research/{quote(conversation, safe='')}/runs/{quote(run, safe='')}"
        f"/evidence/{quote(evidence, safe='')}?view=sources"
    )

    with sync_playwright() as playwright:
        browser_type = getattr(playwright, args.browser)
        browser = browser_type.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 320, "height": 800}, reduced_motion="reduce"
        )
        page = context.new_page()
        response = page.goto(deep_link, wait_until="domcontentloaded", timeout=30_000)
        if response is None or response.status >= 400:
            raise SystemExit(
                f"deep-link navigation failed: status={response.status if response else 'none'}"
            )
        page.get_by_role("navigation", name="Research workspace views").wait_for(timeout=15_000)
        if page.url.split("?", 1)[0] != deep_link.split("?", 1)[0]:
            raise SystemExit("stable research deep link was not preserved")
        if page.locator("html").evaluate("el => el.scrollWidth > el.clientWidth"):
            raise SystemExit("320px viewport has horizontal page overflow")
        page.get_by_role("button", name="Switch to dark theme").click()
        if page.locator("html").get_attribute("data-theme") != "dark":
            raise SystemExit("theme switch did not update the semantic theme")
        page.keyboard.press("Tab")
        focused = page.evaluate("document.activeElement && document.activeElement.tagName")
        if not focused or focused == "BODY":
            raise SystemExit("keyboard focus did not move to an interactive control")

        # 200% layout zoom is a deterministic proxy for browser zoom in the headless gate.
        # Manual screen-reader/browser zoom remains an operator check, but the layout must not
        # introduce horizontal page overflow under magnification.
        page.evaluate("document.documentElement.style.zoom = '200%'")
        page.wait_for_timeout(100)
        if page.locator("html").evaluate("el => el.scrollWidth > el.clientWidth"):
            raise SystemExit("200% zoom introduces horizontal page overflow")
        page.evaluate("document.documentElement.style.zoom = '100%'")

        page.get_by_role("button", name="Answer").click()
        page.get_by_role("button", name="Sources", exact=False).click()
        evidence_button = page.locator(f'[data-evidence-id="{evidence}"]')
        evidence_button.wait_for(timeout=15_000)
        evidence_button.focus()
        evidence_button.click()
        page.get_by_role("dialog").wait_for(timeout=10_000)
        page.keyboard.press("Escape")
        page.get_by_role("dialog").wait_for(state="detached", timeout=10_000)
        if (
            page.evaluate(
                "document.activeElement && document.activeElement.getAttribute('data-evidence-id')"
            )
            != evidence
        ):
            raise SystemExit("evidence drawer did not return keyboard focus to its trigger")

        page.get_by_role("button", name="Compare").click()
        page.get_by_role("button", name="Activity").click()
        event_count = page.locator("[data-run-event]").count()
        if event_count < args.min_activity_events:
            raise SystemExit(
                f"activity replay exposed only {event_count} events; need >= {args.min_activity_events}"
            )
        context.close()
        browser.close()
    print(
        f"PASS browser={args.browser} viewport=320 zoom=200% reduced_motion=reduce deep_link=preserved activity_events>={args.min_activity_events}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
