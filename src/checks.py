"""
src/checks.py
——————————————
CheckoutGuard · Phase 2 — Funnel Automation & Link Audit

Walks the full purchase funnel (sort → cart → checkout → receipt) for
every account that can log in, and audits the three footer social
links. Every check verifies REAL page/DOM state — never assumes an
action "worked" just because no exception was thrown — and every
account produces exactly one CheckResult, success or failure, so
nothing silently vanishes from the report.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import BrowserContext, Error, Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.auth.login import attempt_login, logout
from src.core.config import DEFAULT_TIMEOUT_MS, FINAL_DIR, LOG_DIR, Auth, Url
from src.core.logger import setup_logging


@dataclass
class CheckResult:
    """One structured result per account. Every field has a safe,
    correctly-typed default — no fragile tuple-indexing landmines."""

    account_name: str
    login_success: bool
    checkout_end_to_end: bool = False
    sorted_prices: list[float] = field(default_factory=list)
    is_sorted: bool = False
    order_receipt: Path | None = None
    social_link_tab: list[tuple[str, bool]] = field(default_factory=list)
    notes: str | None = None


# ============================================
# SORT INVENTORY PRICE FROM LOW TO HIGH
# ============================================
def sort_items_low_high(
    option_label: str = "Price (low to high)", *, page: Page, log: logging.Logger
) -> list[float]:
    """Sort the inventory by price and return prices as they ACTUALLY
    appear afterward — reading real DOM state, not trusting the click."""

    if "/inventory.html" not in page.url:
        page.goto(Url.inventory_url, wait_until="domcontentloaded")
        log.info("Loading Inventory page..")

    before = page.locator('[data-test="inventory-item-price"]').all_inner_texts()
    log.info("Before sort: %s", before)

    # sort by selection
    page.locator('[data-test="product-sort-container"]').select_option(
        label=option_label
    )

    after = page.locator('[data-test="inventory-item-price"]').all_inner_texts()

    log.info("After sort: %s", after)

    return [_clean_item_price(p) for p in after]


def is_sorted_from_low_high(prices: list | None) -> bool:
    """
    Confirm prices are sorted from low to high.
    Returns True/False
    """
    if prices is None:
        return False
    is_sorted = all(prices[i] <= prices[i + 1] for i in range(len(prices) - 1))
    return is_sorted


# ========================
#  CART
# ========================


def add_products(page: Page, no_of_clicks: int = 2) -> tuple[list[dict[str, str]], int]:
    """
    Add exactly `no_of_clicks` products to the cart. The number of
    clicks and the number of recorded items must always stay in sync —
    a mismatch here silently poisons every downstream cart check.
    """
    if no_of_clicks < 1:
        raise ValueError(f"no_of_clicks must be at least 1, got {no_of_clicks}")

    inventory_cards = page.locator('[data-test="inventory-item"]').all()[:no_of_clicks]

    if not inventory_cards:
        raise RuntimeError(
            "No inventory items found on the page — is this a real site regression?"
        )

    selected_items: list[dict[str, str]] = []
    for card in inventory_cards:
        item = {
            "item_name": card.locator('[data-test="inventory-item-name"]').inner_text(),
            "price": card.locator('[data-test="inventory-item-price"]').inner_text(),
        }
        button = card.get_by_role("button", name="Add to cart")
        button.click()
        selected_items.append(item)

    return selected_items, len(selected_items)


def _get_no_of_items_cart_badge(page: Page) -> int:
    """
    Read the cart badge count from ITS OWN element — not the cart link
    wrapper, which is always visible whether the cart is empty or not.
    When the cart is empty, SauceDemo renders no badge at all, so an
    absent badge legitimately means zero, not an error.

    NOTE: verify `.shopping_cart_badge` against live DevTools before
    trusting this in production — selectors drift when sites redesign.
    """
    badge = page.locator(".shopping_cart_badge")
    if badge.count() == 0:
        return 0
    return int(badge.inner_text().strip())


def cart_badge_matches_selected_items(
    page: Page, no_of_added_items: int, log: logging.Logger
) -> bool:
    """Confirm the cart badge count matches what we actually added."""
    try:
        badge_count = _get_no_of_items_cart_badge(page)
    except (PlaywrightTimeoutError, Error) as e:
        log.error("Could not read cart badge: %s", e)
        return False
    return no_of_added_items == badge_count


def _cart_items_match_selected_items(
    page: Page, selected_items: list[dict[str, str]]
) -> tuple[bool, list[str]]:
    """
    Compare items actually present on the page against what we clicked.
    """
    all_cart_items: list[str] = []
    rows = page.locator("[data-test='inventory-item']").all()
    for row in rows:
        item_name = row.locator("[data-test='inventory-item-name']").inner_text()
        price = row.locator("[data-test='inventory-item-price']").inner_text()
        all_cart_items.append(f"{item_name}, {price}")

    items_match = all(
        f"{item['item_name']}, {item['price']}" in all_cart_items
        for item in selected_items
    )
    return items_match, all_cart_items


def check_items_in_cart_match_items_selected(
    page: Page, selected_items: list[dict[str, str]], log: logging.Logger
) -> tuple[bool, list[str]]:
    """
    Navigate to the cart page and confirm its contents match what we
    selected. If navigation itself fails, that's a DISTINCT, honest
    failure — we never fall through and read stale data from whatever
    page we happen to still be on.
    """
    try:
        page.locator("[data-test='shopping-cart-link']").click()
        page.wait_for_url("**/cart.html")
    except (PlaywrightTimeoutError, Error) as e:
        log.error("Could not reach the cart page: %s", e)
        return False, []

    return _cart_items_match_selected_items(page, selected_items)


# ——————————————————————————————
# FULL CHECKOUT FUNNEL
# ——————————————————————————————
def check_end_to_end_checkout(
    page: Page,
    no_of_items_added: int,
    firstname: str,
    lastname: str,
    postal_code: str,
    log: logging.Logger,
) -> tuple[bool, Path | None]:
    """
    Walk the full purchase funnel: add items -> verify cart -> checkout
    -> confirm success message -> download the receipt.

    Returns (success, receipt_path). Every failure path returns
    IMMEDIATELY with an accurate, stage-specific log message — never
    falls through to a generic message that misdiagnoses the cause.
    """

    selected_items, count = add_products(page, no_of_items_added)
    log.info("%d products added to cart", count)

    if not cart_badge_matches_selected_items(page, count, log):
        badge_count = _get_no_of_items_cart_badge(page)
        log.error(
            "Cart badge shows %d items, expected %d — aborting before checkout",
            badge_count,
            count,
        )
        return False, None

    cart_items_match, cart_items = check_items_in_cart_match_items_selected(
        page, selected_items, log
    )
    if not cart_items_match:
        log.error(
            "Cart items %s do not match expected selection %s",
            cart_items,
            [f"{i['item_name']}, {i['price']}" for i in selected_items],
        )
        return False, None

    page.get_by_role("button", name="Checkout").click()

    try:
        page.wait_for_url("**/checkout-step-one.html")
        page.get_by_role("textbox", name="First Name").fill(firstname)
        page.get_by_role("textbox", name="Last Name").fill(lastname)
        page.get_by_role("textbox", name="Zip/Postal Code").fill(postal_code)
        page.get_by_role("button", name="Continue").click()
        page.wait_for_url("**/checkout-step-two.html")
    except (PlaywrightTimeoutError, Error) as e:
        log.error("Checkout steps one/two failed: %s", e)
        return False, None

    selected_prices = [_clean_item_price(item["price"]) for item in selected_items]
    expected_total = round(sum(selected_prices) * 1.08, 2)
    actual_total = _clean_item_price(
        page.locator("[data-test='total-label']").inner_text()
    )
    final_items_match, final_cart_items = _cart_items_match_selected_items(
        page, selected_items
    )
    total_matches = expected_total == actual_total

    if not (final_items_match and total_matches):
        log.error(
            "Checkout summary mismatch — items_match=%s, expected_total=%.2f, actual_total=%.2f",
            final_items_match,
            expected_total,
            actual_total,
        )
        return False, None

    page.get_by_role("button", name="Finish").click()

    try:
        page.wait_for_url("**/checkout-complete.html")
    except (PlaywrightTimeoutError, Error) as e:
        log.error("Timeout/error reaching checkout-complete.html: %s", e)
        return False, None

    success_message = page.locator("[data-test='complete-header']").inner_text()
    if "Thank you" not in success_message:
        log.error("Unexpected confirmation message: '%s'", success_message)
        return False, None

    log.info("✅ Checkout end-to-end confirmed: %s", success_message)
    receipt_dir = FINAL_DIR / "reports"
    receipt_dir.mkdir(parents=True, exist_ok=True)

    try:
        with page.expect_download() as download_info:
            page.get_by_role("button", name="Generate PDF order").click()
        download = download_info.value
        receipt_path = receipt_dir / download.suggested_filename
        download.save_as(receipt_path)
        log.info("🧾 Receipt saved -> %s", receipt_path)
    except (PlaywrightTimeoutError, Error) as e:
        # The purchase itself DID succeed — report that honestly even
        # if the receipt download step failed separately.
        log.error("Checkout succeeded but receipt download failed: %s", e)
        return True, None

    return True, receipt_path


# ——————————————————————————————
# FOOTER LINK AUDIT
# ——————————————————————————————
def open_social_link_in_new_tab(
    page: Page, context: BrowserContext, social: str, log: logging.Logger
) -> bool:
    """
    Click a footer social link, confirm it opens a working page in a
    new tab, then close it. A link that fails to open a tab AT ALL is
    just as real a failure as one that opens to a 404 — both must be
    reported, neither should crash the run.
    """
    try:
        with context.expect_page() as new_page_info:
            page.locator(f'[data-test="social-{social}"]').click()
        new_page = new_page_info.value
    except (PlaywrightTimeoutError, Error) as e:
        log.error("'%s' link never opened a new tab: %s", social, e)
        return False

    try:
        new_page.wait_for_load_state("domcontentloaded")
        expected_name = "x.com" if social == "twitter" else f"{social}.com"
        url_ok = expected_name in new_page.url

        if url_ok:
            log.info("✅ '%s' link opened successfully in new tab", social)
            return True

        log.error("❌ '%s' link loaded but failed the title/URL check", social)
        return False

    except (PlaywrightTimeoutError, Error) as e:
        log.error("'%s' tab failed to load correctly: %s", social, e)
        return False
    finally:
        new_page.close()
        log.info("'%s' link tab closed cleanly", social)


# ——————————————————————————————
# ORCHESTRATOR
# ——————————————————————————————
def run_workflow(
    headless: bool = True,
    no_of_items_added: int = 2,
    firstname: str = "Abdulmalik",
    lastname: str = "Abdulsamad",
    postal: str = "50072",
) -> list[CheckResult]:
    """
    Phase 2 orchestrator. Every account produces exactly one
    CheckResult — success, expected-failure, or crash — nothing is
    ever silently dropped from the final report.
    """
    log = setup_logging(LOG_DIR)
    log.info("=== CheckoutGuard Mornitor started ====")

    accounts = [
        ("standard_user", Auth.standard_user),
        ("locked_out_user", Auth.locked_out_user),
        ("problem_user", Auth.problem_user),
        ("performance_glitch_user", Auth.performance_glitch_user),
    ]

    footer_links = ["facebook", "twitter", "linkedin"]

    results: list[CheckResult] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        try:
            for account_name, username in accounts:
                try:
                    login_result = attempt_login(
                        page, account_name, username, Auth.password, log
                    )
                except Exception as e:  # noqa: BLE001 — deliberate: isolate the batch
                    log.exception(
                        "Unhandled error logging in '%s': %s", account_name, e
                    )
                    results.append(
                        CheckResult(
                            account_name,
                            login_success=False,
                            notes=f"Login crashed: {e}",
                        )
                    )
                    continue

                if not login_result.success:
                    log.info(
                        "Skipping funnel checks for '%s' — login failed as expected",
                        account_name,
                    )
                    results.append(
                        CheckResult(
                            account_name,
                            login_success=False,
                            notes=f"Skipped — login failed: {login_result.error_message}",
                        )
                    )
                    continue

                result = CheckResult(account_name, login_success=True)

                try:
                    sorted_prices = sort_items_low_high(page=page, log=log)
                    result.sorted_prices = sorted_prices
                    result.is_sorted = is_sorted_from_low_high(sorted_prices)
                    log.info(
                        "Prices %s sorted confirmed: %s",
                        [f"{p:.2f}" for p in sorted_prices],
                        result.is_sorted,
                    )

                    checkout_ok, receipt_path = check_end_to_end_checkout(
                        page, no_of_items_added, firstname, lastname, postal, log
                    )
                    result.checkout_end_to_end = checkout_ok
                    result.order_receipt = receipt_path

                    for link in footer_links:
                        link_ok = open_social_link_in_new_tab(page, context, link, log)
                        result.social_link_tab.append((link, link_ok))

                except Exception as e:  # noqa: BLE001 — isolate the batch
                    log.exception(
                        "Unhandled error during checks for '%s': %s", account_name, e
                    )
                    result.notes = f"Crashed mid-check: {e}"

                results.append(result)
                logout(page, log)

        finally:
            context.close()
            browser.close()
            log.info("Browser closed cleanly")

    _print_summary(results, log)
    return results


# ——————————————————————————————
# HELPERS
# ——————————————————————————————
def _clean_item_price(item_price: str) -> float:
    clean_item_price = float(re.sub(r"[^\d.]", "", item_price.strip()))
    return clean_item_price


def _print_summary(results: list[CheckResult], log: logging.Logger) -> None:
    log.info("════════════════════════════════════════")
    log.info("PHASE 2 RUN SUMMARY")
    for r in results:
        passed = r.login_success and r.checkout_end_to_end and r.is_sorted
        status = "✅ PASS" if passed else "❌ FAIL"
        receipt_note = f"🧾 {r.order_receipt}" if r.order_receipt else "no receipt"
        log.info(
            "  [%s] %-26s sorted=%-5s checkout=%-5s links=%s -> %s%s",
            status,
            r.account_name,
            r.is_sorted,
            r.checkout_end_to_end,
            r.social_link_tab,
            receipt_note,
            f" | {r.notes}" if r.notes else "",
        )
    passed_count = sum(
        r.login_success and r.checkout_end_to_end and r.is_sorted for r in results
    )
    log.info("  %d/%d accounts passed the full funnel", passed_count, len(results))
    log.info(
        "CheckoutGuard Monitor complete. Receipts saved to -> %s",
        str(FINAL_DIR / "reports"),
    )
    log.info("════════════════════════════════════════")
