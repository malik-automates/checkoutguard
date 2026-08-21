"""
src/auth.py

"""

# stdlib
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

# third-party
from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# project-modules
from src.core.config import DEFAULT_TIMEOUT_MS, LOG_DIR, SCREENSHOT_DIR, Auth, Url
from src.core.logger import setup_logging

# timeout for specific page
INVENTORY_WAIT_MS = 15_000
ERROR_BANNER_WAIT_MS = 3000


@dataclass
class LoginAttemptResult:
    account_name: str
    success: bool
    error_message: str | None
    duration_ms: float
    screenshot: Path | None = None


def attempt_login(
    page: Page,
    account_name: str,
    username: str,
    password: str,
    log: logging.Logger,
) -> LoginAttemptResult:
    """
    Attempt to log in with ONE account and return a structured result.

    We race two REAL outcomes instead of guessing from the username:
        1. The app navigates to /inventory.html  → success
        2. A login error banner appears           → handled failure
    Anything else (neither happens) is surfaced honestly as an
    unrecognised failure — never silently swallowed, never crashed on.
    """
    log.info("————— Attempting to login: %s —————", account_name)
    page.goto(Url.login_url, wait_until="domcontentloaded")

    start_time = time.perf_counter()
    page.get_by_role("textbox", name="Username").fill(username)
    page.get_by_role("textbox", name="Password").fill(password)

    log.info("login credentials entered")
    page.get_by_role("button", name="Login").click()

    error_locator = page.locator('[data-test="error"]')

    try:
        page.wait_for_url("**/inventory.html")
    except PlaywrightTimeoutError:
        duration_ms = (time.perf_counter() - start_time) * 1000
        try:
            error_locator.wait_for(state="visible")
            error_text = error_locator.inner_text().strip()
            log.warning("Login failed for '%s': %s", account_name, error_text)
            return LoginAttemptResult(account_name, False, error_text, duration_ms)
        except PlaywrightTimeoutError:
            # Neither the inventory page NOR a known error banner showed
            # up — a genuinely unexpected state. Surface it honestly
            # instead of hiding it or crashing the whole batch.
            log.error(
                "Login for '%s' timed out with no recognisable error banner",
                account_name,
            )
            return LoginAttemptResult(
                account_name,
                False,
                "Unrecognize failure: no navigation and no error banner detecdted",
                duration_ms,
            )

    duration_ms = (time.perf_counter() - start_time) * 1000
    log.info("✅ Login succeeded for '%s' in %.0fms", account_name, duration_ms)
    return LoginAttemptResult(account_name, True, None, duration_ms)


def logout(page: Page, log: logging.Logger) -> None:
    log.info("Log out from the inventory page and confirm we are back at login page")
    page.get_by_role("button", name="Open Menu").click()
    logout_link = page.get_by_role("link", name="Logout")
    logout_link.click()
    page.wait_for_url("**/")
    log.info("logout - back at %s", page.url)


def capture_proof_screenshot(
    page: Page, account_name: str, success: bool, screenshot_dir: Path
) -> Path:
    """Save a full page PNG as proof of run for one login attempt."""
    status = "success" if success else "failure"
    filename = f"{account_name}_login_{status}.png"
    path = SCREENSHOT_DIR / filename
    page.screenshot(path=path, full_page=True)
    return path


def run_attempt_login(
    headless: bool = True,
) -> list[LoginAttemptResult]:
    """
    Run the full Phase 1 health check: attempt login with every test
    account, capture proof for each, and return one LoginAttemptResult
    per account — regardless of whether an individual attempt failed
    OR crashed outright. One broken account never takes down the batch.
    """
    log = setup_logging(LOG_DIR)
    log.info("══════ Authentication phase started ══════")

    accounts = [
        ("standard_user", Auth.standard_user),
        ("locked_out_user", Auth.locked_out_user),
        ("problem_user", Auth.problem_user),
        ("performance_glitch_user", Auth.performance_glitch_user),
    ]

    results: list[LoginAttemptResult] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        try:
            for account_name, username in accounts:
                try:
                    result = attempt_login(
                        page, account_name, username, Auth.password, log
                    )
                except Exception as e:
                    log.exception(
                        "Unhandled error while testing '%s':%s", account_name, e
                    )
                    result = LoginAttemptResult(
                        account_name, False, f"Unhandled exception: {e}", 0.0
                    )

                screenshot_path = capture_proof_screenshot(
                    page, account_name, result.success, SCREENSHOT_DIR
                )
                result.screenshot = screenshot_path
                log.info("Proof-of-run screenshot -> %s", screenshot_path)
                results.append(result)

                if result.success:
                    logout(page, log)

        finally:
            context.close()
            browser.close()
            log.info("Browser closed cleanly")

    _print_summary(results, log)
    return results


def _print_summary(results: list[LoginAttemptResult], log: logging.Logger):
    log.info("════════════════════════════════════════")
    log.info("PHASE 1 RUN SUMMARY")
    for r in results:
        status = "PASS" if r.success else "FAIL"
        log.info(
            "  [%s] %-26s %6.0fms %s",
            status,
            r.account_name,
            r.duration_ms,
            r.error_message or "",
        )
    passed = sum(r.success for r in results)
    log.info("  %d/%d accounts behaved as expected", passed, len(results))
    log.info("════════════════════════════════════════")
