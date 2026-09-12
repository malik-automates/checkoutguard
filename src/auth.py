"""
src/auth.py

"""

from __future__ import annotations

import logging
from pathlib import Path

from playwright.sync_api import Browser, BrowserContext, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.core.config import DEFAULT_TIMEOUT_MS, LOGIN_URL, PortalConfig, Url
from src.core.retry import retry_action

INVENTORY_WAIT_MS = 15_000
ERROR_BANNER_WAIT_MS = 3_000


def attempt_login(
    browser: Browser,
    config: PortalConfig,
    username: str,
    password: str,
    log: logging.Logger,
) -> tuple[BrowserContext | None, bool, str | None]:
    """
    Attempt to log in with ONE account.

    Detection is based on REAL page state after submitting the form —
    either the app navigates to /inventory.html (success), or a login
    error banner appears (a handled, expected failure). We never check
    page.url immediately after a click (navigation is asynchronous —
    that's a race condition), and we never infer the outcome from the
    username string.

    Returns (context, success, error_message). On failure, `context`
    is never a context that's already been closed.
    """

    def _login() -> tuple[BrowserContext, bool, str | None]:
        log.info("————— Attempting to login: %s —————", username)
        context = browser.new_context()
        try:
            page = context.new_page()
            page.goto(
                LOGIN_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS
            )

            page.get_by_role("textbox", name="Username").fill(username)
            page.get_by_role("textbox", name="Password").fill(password)
            log.info("login credentials entered")
            page.get_by_role("button", name="Login").click()

            try:
                page.wait_for_url("**/inventory.html", timeout=INVENTORY_WAIT_MS)
            except PlaywrightTimeoutError:
                error_locator = page.locator("[data-test='error']")
                try:
                    error_locator.wait_for(
                        state="visible", timeout=ERROR_BANNER_WAIT_MS
                    )
                    error_text = error_locator.inner_text().strip()
                    log.warning("Login failed for '%s': %s", username, error_text)
                    return context, False, error_text
                except PlaywrightTimeoutError:
                    # Neither success nor a recognised error banner —
                    # a genuinely unexpected state. Worth retrying.
                    context.close()
                    raise

            log.info("✓ Fresh login succeeded for '%s'", username)
            return context, True, None

        except Exception:
            # Any failure on THIS attempt must not leak into the next
            # retry — close before re-raising.
            context.close()
            raise

    return retry_action(
        _login,
        description="fresh login",
        log=log,
        retries=config.max_retries,
        backoff_base=config.backoff_base,
    )


def is_session_valid(context: BrowserContext) -> bool:
    """
    Prove a session is genuinely still authenticated by visiting a
    protected page directly. Any failure here (timeout, aborted
    connection — this exact site has produced both before) means
    "don't trust this session," never "crash the whole run."
    """
    try:
        page = context.new_page()
        page.goto(
            Url.inventory_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS
        )
        valid = "/inventory.html" in page.url
        page.close()
        return valid
    except Exception:
        return False


def get_authenticated_context(
    browser: Browser,
    config: PortalConfig,
    username: str,
    password: str,
    log: logging.Logger,
) -> tuple[BrowserContext | None, bool, str | None]:
    """
    Produce ONE context for the caller to own for the rest of the run
    — including attaching tracing to it. Tries to reuse a saved
    session first; falls back to a fresh login.

    Returns (context, login_success, error_message).
    """
    config.auth.session_user = username  # update before declaring session file
    session_file = config.auth.state_file()
    if not config.force_relogin and session_file.exists():
        log.info("Attempting to reuse saved session -> %s", session_file)
        candidate = browser.new_context(storage_state=str(session_file))
        if is_session_valid(candidate):
            log.info("✓ Session reused - login step skipped entirely")
            return candidate, True, None
        log.warning("Saved session expired or invalid - logging in fresh")
        candidate.close()

    context, success, error_message = attempt_login(
        browser, config, username, password, log
    )
    if success and context is not None:
        context.storage_state(path=str(session_file))
        log.info("Session saved -> %s", session_file)
    return context, success, error_message


def logout(page: Page, log: logging.Logger) -> None:
    log.info("Log out from the inventory page and confirm we are back at login page")
    page.get_by_role("button", name="Open Menu").click()
    logout_link = page.get_by_role("button", name="Logout")
    logout_link.click()
    page.wait_for_url("**/")
    log.info("logout - back at %s", page.url)


def capture_proof_screenshot(
    page: Page, account_name: str, success: bool, screenshot_dir: Path
) -> Path:
    """Save a full-page PNG as proof-of-run — uses the CALLER's
    directory, not a hardcoded module constant."""
    status = "success" if success else "failure"
    filename = f"{account_name}_login_{status}.png"
    path = screenshot_dir / filename
    page.screenshot(path=path, full_page=True)
    return path
