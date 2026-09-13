"""Offline tests for every function in :mod:`src.checks`.

The page doubles below model the DOM values and Playwright interactions used by
SauceDemo. No browser is launched and no network request is made.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from playwright.sync_api import Error
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

project_root = str(Path(__file__).parent.parent)
sys.path.insert(0, project_root)

from src.checks import (
    _cart_items_match_selected_items,
    _clean_item_price,
    _get_no_of_items_cart_badge,
    add_products,
    cart_badge_matches_selected_items,
    check_end_to_end_checkout,
    check_items_in_cart_match_items_selected,
    is_sorted_from_low_high,
    open_social_link_in_new_tab,
    sort_items_low_high,
)
from src.core.config import Auth, PortalConfig, Url

LOGGER = logging.getLogger("offline-checks")
CONFIG = PortalConfig(
    auth=Auth(),
    url=Url(inventory_url="https://offline.test/inventory.html"),
    max_retries=1,
    backoff_base=0,
)


class StaticCard:
    """Small DOM-like object for one static inventory/cart item."""

    def __init__(self, name: str, price: str) -> None:
        self.name = name
        self.price = price
        self.add_button = MagicMock(name="add_to_cart")
        self.add_button.count.return_value = 1

    def locator(self, selector: str) -> SimpleNamespace:
        value = self.name if "inventory-item-name" in selector else self.price
        return SimpleNamespace(count=lambda: 1, inner_text=lambda: value)

    def get_by_role(self, role: str, name: str) -> MagicMock:
        assert (role, name) == ("button", "Add to cart")
        return self.add_button


class StaticPage:
    """Offline page double backed by static inventory/checkout values."""

    def __init__(self, cards: list[StaticCard] | None = None) -> None:
        self.url = "https://offline.test/inventory.html"
        self.cards = cards or []
        self.badge_text: str | None = None
        self.sort_values = [card.price for card in self.cards]
        self.total_text = "Total: $0.00"
        self.complete_text = "Thank you for your order!"
        self.locator_calls: list[str] = []
        self.roles: dict[tuple[str, str], MagicMock] = {}
        self.sort_container = MagicMock()
        self.cart_link = MagicMock()
        self.social_link = MagicMock()
        self.download = SimpleNamespace(
            suggested_filename="offline-order.pdf",
            save_as=MagicMock(name="save_as"),
        )

    def locator(self, selector: str) -> MagicMock | SimpleNamespace:
        self.locator_calls.append(selector)
        if (
            selector == '[data-test="inventory-item"]'
            or selector == "[data-test='inventory-item']"
        ):
            locator = MagicMock()
            locator.all.return_value = self.cards
            return locator
        if selector == '[data-test="inventory-item-price"]':
            locator = MagicMock()
            locator.all_inner_texts.return_value = self.sort_values
            return locator
        if selector == '[data-test="product-sort-container"]':
            return self.sort_container
        if selector == ".shopping_cart_badge":
            locator = MagicMock()
            locator.count.return_value = int(self.badge_text is not None)
            locator.inner_text.return_value = self.badge_text or ""
            return locator
        if selector == "[data-test='total-label']":
            return SimpleNamespace(inner_text=lambda: self.total_text)
        if selector == "[data-test='complete-header']":
            return SimpleNamespace(inner_text=lambda: self.complete_text)
        if selector == "[data-test='shopping-cart-link']":
            return self.cart_link
        if selector.startswith('[data-test="social-'):
            return self.social_link
        raise AssertionError(f"Unexpected selector: {selector}")

    def get_by_role(self, role: str, name: str) -> MagicMock:
        return self.roles.setdefault((role, name), MagicMock(name=name))

    def wait_for_url(self, pattern: str) -> None:
        if pattern == "**/cart.html":
            self.url = "https://offline.test/cart.html"
        elif pattern == "**/checkout-step-one.html":
            self.url = "https://offline.test/checkout-step-one.html"
        elif pattern == "**/checkout-step-two.html":
            self.url = "https://offline.test/checkout-step-two.html"
        elif pattern == "**/checkout-complete.html":
            self.url = "https://offline.test/checkout-complete.html"

    @contextmanager
    def expect_download(self):
        yield SimpleNamespace(value=self.download)

    def goto(self, url: str, wait_until: str) -> None:
        self.url = url

    def close(self) -> None:
        pass


@pytest.fixture
def inventory_page() -> Any:
    page = StaticPage(
        [
            StaticCard("Sauce Labs Backpack", "$29.99"),
            StaticCard("Sauce Labs Bike Light", "$9.99"),
            StaticCard("Sauce Labs Bolt T-Shirt", "$15.99"),
        ]
    )
    page.sort_container = MagicMock()
    page.cart_link = MagicMock()
    page.social_link = MagicMock()
    return page


def test_clean_item_price_parses_static_dom_text() -> None:
    assert _clean_item_price("Total: $1,234.56") == 1234.56


def test_is_sorted_from_low_high_handles_valid_and_invalid_prices() -> None:
    assert is_sorted_from_low_high([9.99, 15.99, 29.99])
    assert not is_sorted_from_low_high([15.99, 9.99, 29.99])
    assert is_sorted_from_low_high([])
    assert not is_sorted_from_low_high(None)


def test_sort_items_low_high_reads_prices_after_selecting_option(
    inventory_page,
) -> None:
    inventory_page.sort_values = ["$9.99", "$15.99", "$29.99"]

    prices = sort_items_low_high(page=inventory_page, log=LOGGER)

    assert prices == [9.99, 15.99, 29.99]
    inventory_page.sort_container.select_option.assert_called_once_with(
        label="Price (low to high)"
    )


def test_add_products_clicks_exactly_requested_static_cards(
    inventory_page,
) -> None:
    selected, count = add_products(inventory_page, CONFIG, LOGGER, no_of_clicks=2)

    assert selected == [
        {"item_name": "Sauce Labs Backpack", "price": "$29.99"},
        {"item_name": "Sauce Labs Bike Light", "price": "$9.99"},
    ]
    assert count == 2
    assert all(
        card.add_button.click.call_count == 1 for card in inventory_page.cards[:2]
    )
    assert inventory_page.cards[2].add_button.click.call_count == 0


def test_get_no_of_items_cart_badge_reads_badge_and_missing_badge_as_zero(
    inventory_page,
) -> None:
    inventory_page.badge_text = " 2 "
    assert _get_no_of_items_cart_badge(inventory_page) == 2
    inventory_page.badge_text = None
    assert _get_no_of_items_cart_badge(inventory_page) == 0


def test_cart_badge_matches_selected_items_handles_value_and_playwright_error(
    inventory_page,
) -> None:
    inventory_page.badge_text = "2"
    assert cart_badge_matches_selected_items(inventory_page, 2, LOGGER)
    assert not cart_badge_matches_selected_items(inventory_page, 1, LOGGER)
    with patch(
        "src.checks._get_no_of_items_cart_badge", side_effect=Error("DOM failed")
    ):
        assert not cart_badge_matches_selected_items(inventory_page, 2, LOGGER)


def test_cart_items_match_selected_items_reads_static_cart_rows(
    inventory_page,
) -> None:
    selected = [{"item_name": "Sauce Labs Backpack", "price": "$29.99"}]
    matches, rows = _cart_items_match_selected_items(inventory_page, selected, LOGGER)

    assert matches
    assert rows == [
        "Sauce Labs Backpack, $29.99",
        "Sauce Labs Bike Light, $9.99",
        "Sauce Labs Bolt T-Shirt, $15.99",
    ]


def test_check_items_in_cart_match_items_selected_navigates_and_reports_rows(
    inventory_page,
) -> None:
    selected = [{"item_name": "Sauce Labs Backpack", "price": "$29.99"}]
    result = check_items_in_cart_match_items_selected(inventory_page, selected, LOGGER)

    assert result == (
        True,
        [
            "Sauce Labs Backpack, $29.99",
            "Sauce Labs Bike Light, $9.99",
            "Sauce Labs Bolt T-Shirt, $15.99",
        ],
    )
    inventory_page.cart_link.click.assert_called_once()
    assert inventory_page.url.endswith("/cart.html")


def test_check_items_in_cart_match_items_selected_returns_failure_on_navigation_error(
    inventory_page,
) -> None:
    inventory_page.cart_link.click.side_effect = PlaywrightTimeoutError(
        "offline timeout"
    )

    assert check_items_in_cart_match_items_selected(
        inventory_page,
        [{"item_name": "Sauce Labs Backpack", "price": "$29.99"}],
        LOGGER,
    ) == (False, [])


def _checkout_page() -> Any:
    page = StaticPage([StaticCard("Sauce Labs Bike Light", "$9.99")])
    page.badge_text = "1"
    page.sort_container = MagicMock()
    page.cart_link = MagicMock()
    page.social_link = MagicMock()
    page.total_text = "Total: $10.79"
    return page


def test_check_end_to_end_checkout_completes_offline_funnel(tmp_path: Path) -> None:
    page = _checkout_page()
    selected = [{"item_name": "Sauce Labs Bike Light", "price": "$9.99"}]
    with (
        patch("src.checks.FINAL_DIR", tmp_path),
        patch("src.checks.add_products", return_value=(selected, 1)),
        patch("src.checks.cart_badge_matches_selected_items", return_value=True),
        patch(
            "src.checks.check_items_in_cart_match_items_selected",
            return_value=(True, ["Sauce Labs Bike Light, $9.99"]),
        ),
        patch(
            "src.checks._cart_items_match_selected_items",
            return_value=(True, ["Sauce Labs Bike Light, $9.99"]),
        ),
    ):
        success, receipt = check_end_to_end_checkout(
            page, CONFIG, 1, "Ada", "Lovelace", "12345", LOGGER
        )

    assert success
    assert receipt == tmp_path / "reports" / "offline-order.pdf"
    page.get_by_role("textbox", name="First Name").fill.assert_called_once_with("Ada")
    page.get_by_role("textbox", name="Last Name").fill.assert_called_once_with(
        "Lovelace"
    )
    page.get_by_role("textbox", name="Zip/Postal Code").fill.assert_called_once_with(
        "12345"
    )
    page.download.save_as.assert_called_once_with(receipt)


def test_open_social_link_in_new_tab_validates_url_and_closes_tab() -> None:
    page = MagicMock()
    context = MagicMock()
    social_page = MagicMock()
    social_page.url = "https://x.com/saucelabs"
    context.expect_page.return_value.__enter__.return_value.value = social_page

    assert open_social_link_in_new_tab(page, context, CONFIG, "x", LOGGER)
    page.locator.assert_called_once_with('[data-test="social-x"]')
    social_page.close.assert_called_once()
    page.close.assert_not_called()


def test_open_social_link_in_new_tab_rejects_wrong_destination() -> None:
    page = MagicMock()
    context = MagicMock()
    social_page = MagicMock()
    social_page.url = "https://example.test/not-twitter"
    context.expect_page.return_value.__enter__.return_value.value = social_page

    with pytest.raises(ValueError, match="unexpected URL"):
        open_social_link_in_new_tab(page, context, CONFIG, "x", LOGGER)
    social_page.close.assert_called_once()
