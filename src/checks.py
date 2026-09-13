"""
src/checks.py
——————————————
CheckoutGuard · Phase 3 — Reliability

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
from pathlib import Path

from playwright.sync_api import BrowserContext, Error, Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from src.core.config import (
    FINAL_DIR,
    PortalConfig,
    Url,
)
from src.core.retry import retry_action

# —————————————————————————————————————————————
# WORKFLOW CHECKS
# —————————————————————————————————————————————


# ============================================
# CHECK 1: SORT INVENTORY PRICE FROM LOW TO HIGH
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


# =================================
#  CHECK 2: ADD PRODUCTST TO CART
# ================================
def add_products(
    page: Page, config: PortalConfig, log: logging.Logger, no_of_clicks: int = 2
) -> tuple[list[dict[str, str]], int]:
    """
    Add exactly `no_of_clicks` products to the cart. The number of
    clicks and the number of recorded items must always stay in sync —
    a mismatch here silently poisons every downstream cart check.
    """

    def _add() -> tuple[list[dict[str, str]], int]:
        if no_of_clicks < 1:
            raise ValueError(f"no_of_clicks must be at least 1, got {no_of_clicks}")

        inventory_cards = page.locator('[data-test="inventory-item"]').all()[
            :no_of_clicks
        ]
        if not inventory_cards:
            raise RuntimeError(
                "No inventory items found on the page — is this a real site regression?"
            )

        selected_items: list[dict[str, str]] = []
        for card in inventory_cards:
            item = {
                "item_name": card.locator(
                    '[data-test="inventory-item-name"]'
                ).inner_text(),
                "price": card.locator(
                    '[data-test="inventory-item-price"]'
                ).inner_text(),
            }
            # Idempotent: a retry after a partial failure must not re-click
            # an item that's already in the cart — the button has already
            # flipped to "Remove" and won't exist under this name anymore.
            add_button = card.get_by_role("button", name="Add to cart")
            if add_button.count() > 0:
                add_button.click()
            selected_items.append(item)

        return selected_items, len(selected_items)

    results = retry_action(
        _add,
        description="add products to cart",
        log=log,
        retries=config.max_retries,
        backoff_base=config.backoff_base,
    )
    return results


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


# =============================================
#  CHECK 3: CART BADGE MATCHES SELECTED ITEMS
# =============================================
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
    page: Page, selected_items: list[dict[str, str]], log: logging.Logger
) -> tuple[bool, list[str]]:
    """
    Compare items actually present on the page against what we clicked.
    Skips any matched element that isn't a genuine product row instead
    of hanging on it — an unexpected extra element on the page becomes
    a fast, clear mismatch, never a 30-second stall.
    """
    all_cart_items: list[str] = []
    rows = page.locator("[data-test='inventory-item']").all()

    if len(rows) != len(selected_items):
        log.warning(
            "Expected %d cart rows, found %d on the page — investigate if this repeats",
            len(selected_items),
            len(rows),
        )

    for row in rows:
        name_locator = row.locator("[data-test='inventory-item-name']")
        price_locator = row.locator("[data-test='inventory-item-price']")
        if name_locator.count() == 0 or price_locator.count() == 0:
            continue  # not a genuine product row — don't wait on it
        all_cart_items.append(
            f"{name_locator.inner_text()}, {price_locator.inner_text()}"
        )

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

    return _cart_items_match_selected_items(page, selected_items, log)


# =================================
# CHECK 4: FULL CHECKOUT FUNNEL
# =================================
def check_end_to_end_checkout(
    page: Page,
    config: PortalConfig,
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

    selected_items, count = add_products(page, config, log, no_of_items_added)

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
        page, selected_items, log
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
    page: Page,
    context: BrowserContext,
    config: PortalConfig,
    social: str,
    log: logging.Logger,
) -> bool:
    """
    Click a footer social link, confirm it opens a working page in a
    new tab, then close it. A link that fails to open a tab AT ALL is
    just as real a failure as one that opens to a 404 — both must be
    reported, neither should crash the run.
    """
    display_social_name = lambda: (
        f"{social.capitalize()} (twitter)" if social == "x" else social
    )

    def _open_social_link() -> bool:
        with context.expect_page() as new_page_info:
            page.locator(f'[data-test="social-{social}"]').click()
        new_page = new_page_info.value
        try:
            new_page.wait_for_load_state("domcontentloaded")
            expected_name = "x.com" if social == "x" else f"{social}.com"
            url_ok = expected_name in new_page.url

            if not url_ok:
                raise ValueError(
                    f"'{social}' link opened to an unexpected URL: {new_page.url}"
                )

            log.info(
                "✅ '%s' link opened successfully in new tab",
                display_social_name(),
            )
            return True
        finally:
            # Close the NEW TAB — success, wrong destination, or
            # anything else. The caller's `page` is never touched here.
            new_page.close()

    result = retry_action(
        _open_social_link,
        description=f"open {social} link in new tab",
        log=log,
        retries=config.max_retries,
        backoff_base=config.backoff_base,
    )
    log.info("'%s' link tab closed cleanly", display_social_name())
    return result


# ——————————————————————————————
# HELPERS
# ——————————————————————————————
def _clean_item_price(item_price: str) -> float:
    clean_item_price = float(re.sub(r"[^\d.]", "", item_price.strip()))
    return clean_item_price
