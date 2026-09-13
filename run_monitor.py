"""./run_monitor.py"""

import logging
import sys
from datetime import datetime, timezone

from playwright.sync_api import Browser, Error, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.auth import capture_proof_screenshot, get_authenticated_context, logout
from src.checks import (
    check_end_to_end_checkout,
    is_sorted_from_low_high,
    open_social_link_in_new_tab,
    sort_items_low_high,
)
from src.command import build_arg_parse
from src.core.config import (
    SCREENSHOT_DIR,
    TRACE_DIR,
    Auth,
    PortalConfig,
    Url,
    ensure_project_directories,
)
from src.core.logger import setup_logging
from src.report import CheckResult, HealthCheckReport

FOOTER_LINKS = ["facebook", "x", "linkedin"]

all_issues: list = []


def run_account(
    browser: Browser,
    config: PortalConfig,
    username: str,
    password: str,
    log: logging.Logger,
    no_of_items_added: int = 2,
    firstname: str = "Abdulmalik",
    lastname: str = "Abdulsamad",
    postal: str = "50072",
) -> HealthCheckReport:
    """
    Run the full funnel for ONE account, entirely inside ONE context
    that this function owns start to finish — the same context gets
    traced, checked, and closed. Nothing downstream ever touches a
    different context than the one login actually happened on.
    """
    check = CheckResult(username)
    report = HealthCheckReport(check)

    context, login_success, login_error = get_authenticated_context(
        browser, config, username, password, log
    )

    if context is None:
        report.add_issue(
            "Browser context failed: Checkoutguard monitor cannot be initiated"
        )
        log.info("Application crashed: Failed to render context for %s", username)
        return report

    if not login_success:
        msg = f"Login for {username} failed : {login_error}"
        report.add_issue(msg)
        all_issues.append(msg)
        log.info("Skipping funnel checks for '%s' — login failed", username)
        if context is not None:
            context.close()
        return report

    report.check.login_success = login_success

    # Trace THIS context from here on — the one that actually does the
    # work. Discarded on success, saved only if something fails.
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.set_default_timeout(config.timeout_ms)
    capture_proof_screenshot(page, username, True, SCREENSHOT_DIR)

    had_failures = False
    try:
        try:
            report.steps_attempted += 1
            sorted_prices = sort_items_low_high(page=page, log=log)
            report.check.sorted_prices = sorted_prices
            report.check.is_sorted = is_sorted_from_low_high(sorted_prices)
            report.steps_succeeded += 1
        except (PlaywrightTimeoutError, Error) as e:
            log.error("Step 'sort' failed for '%s': %s", username, e)
            report.steps_failed += 1
            report.add_issue(f"Sort failed: {e}")
            had_failures = True
            all_issues.append(f"Sort failed for {username}: {e}")

        try:
            report.steps_attempted += 1
            checkout_ok, receipt_path = check_end_to_end_checkout(
                page, config, no_of_items_added, firstname, lastname, postal, log
            )
            report.check.checkout_end_to_end = checkout_ok
            report.check.order_receipt = receipt_path
            report.steps_succeeded += 1
            had_failures = had_failures or not checkout_ok
        except (PlaywrightTimeoutError, Error) as e:
            log.error("Step 'checkout' failed for '%s': %s", username, e)
            report.steps_failed += 1
            report.add_issue(f"Checkout failed: {e}")
            had_failures = True
            all_issues.append(f"Checkout failed for {username}: {e}")

        for link in FOOTER_LINKS:
            try:
                report.steps_attempted += 1
                link_ok = open_social_link_in_new_tab(page, context, config, link, log)
                report.check.social_link_tab.append((link, link_ok))
                report.steps_succeeded += 1
                had_failures = had_failures or not link_ok
            except Exception as e:
                log.error("Step '%s link' failed for '%s': %s", link, username, e)
                report.steps_failed += 1
                report.add_issue(f"{link} link failed: {e}")
                had_failures = True
                all_issues.append(f"{link} failed for {username} : {e}")

        try:
            logout(page, log)
        except Exception as e:
            log.error("Logout failed for '%s': %s", username, e)
            report.add_issue(f"Logout failed: {e}")
            had_failures = True
            all_issues.append(f"Logout failed: {e}")

    finally:
        if had_failures:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            trace_path = TRACE_DIR / f"trace_failure_{username}_{timestamp}.zip"
            context.tracing.stop(path=trace_path)
            log.error("Full trace saved for debugging -> %s", trace_path)
            log.info("Inspect it with: playwright show-trace %s", trace_path)
        else:
            context.tracing.stop()
            log.info("✓ '%s' succeeded — trace discarded, nothing to debug", username)
        context.close()

    return report


def print_summary(report: HealthCheckReport, log: logging.Logger) -> None:
    log.info("════════════════════════════════════════")
    log.info("CheckoutGuard Run Summary for '%s' account", report.check.username)
    log.info("  Login success       : %s", report.check.login_success)
    log.info("  Sorted prices       : %s", report.check.sorted_prices)
    log.info("  Sort confirmed      : %s", report.check.is_sorted)
    log.info("  Checkout end-to-end : %s", report.check.checkout_end_to_end)
    log.info("  Receipt             : %s", report.check.order_receipt)
    log.info("  Footer links        : %s", report.check.social_link_tab)
    log.info("  Steps attempted     : %d", report.steps_attempted)
    log.info("  Steps succeeded     : %d", report.steps_succeeded)
    log.info("  Steps failed        : %d", report.steps_failed)
    for issue in report.issues:
        log.info("  Issue: %s", issue)
    log.info("════════════════════════════════════════")


def main() -> None:
    args = build_arg_parse().parse_args()
    config = PortalConfig(
        auth=Auth(),
        url=Url(),
        headless=(args.headless == "true"),
        max_retries=args.max_retries,
        backoff_base=args.backoff_base,
        force_relogin=args.force_relogin,
    )
    config.timeout_ms = config.resolve_timeout(args.timeout)
    ensure_project_directories(config)
    log = setup_logging(config.log_dir, args.log_level)
    log.info("=== CheckoutGuard Monitor v1.0 started ====")

    accounts = [
        ("standard_user", Auth.standard_user),
        ("locked_out_user", Auth.locked_out_user),
        ("problem_user", Auth.problem_user),
        ("performance_glitch_user", Auth.performance_glitch_user),
    ]

    overall_failed = False

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=config.headless)
        try:
            for account_name, username in accounts:
                try:
                    report = run_account(browser, config, username, Auth.password, log)
                except Exception as e:
                    log.exception(
                        "Unhandled error running account '%s': %s", account_name, e
                    )
                    overall_failed = True
                    continue
                print_summary(report, log)
                overall_failed = overall_failed or report.steps_failed > 0
        finally:
            browser.close()
            log.info("Browser closed cleanly\n")

    issues = [issue for issue in all_issues if Auth.locked_out_user not in issue]
    if len(issues) > 0:
        log.info(f"Total No. of issues found: {len(issues)}")
        log.info("=== Issue Summary ===")
        for i, issue in enumerate(issues, 1):
            log.info(f"❌ - {i} : {issue} ")
    else:
        log.info("✅ CheckoutGuard Monitor v1.0 complete. NO issues found!")

    sys.exit(1 if overall_failed else 0)


if __name__ == "__main__":
    main()
