# =============================
#  RETRY
# =============================

import logging
import time
from collections.abc import Callable
from typing import TypeVar

# Third-party library
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

# project module
from src.core.exception import TransientStepError

T = TypeVar("T")


def retry_action(
    action: Callable[[], T],
    *,
    description: str,
    log: logging.Logger,
    retries: int = 3,
    backoff_base: float = 1.5,
) -> T:
    last_exception: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return action()
        except (PlaywrightTimeoutError, TransientStepError) as e:
            last_exception = e
            log.warning(
                "Attempt %d/%d failed for '%s': %s", attempt, retries, description, e
            )
            if attempt < retries:
                sleep_for = backoff_base * attempt
                log.info("Retrying '%s' in %.1fs...", description, sleep_for)
                time.sleep(sleep_for)

    log.error("'%s' failed after %d attempts — giving up", description, retries)
    raise last_exception  # type: ignore
