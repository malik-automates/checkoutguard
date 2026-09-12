"""Shared configuration for Checkguard.

This module is the single source of truth for paths, target URLs, browser
timeouts, credentials, and run-level options used by the monitoring scripts.
Values are loaded when the module is imported. The ``Auth`` fields can be
overridden with environment variables, which are typically supplied through a
local ``.env`` file. Do not commit credentials or other secrets to source
control.

Paths are represented by :class:`pathlib.Path` so callers can build paths
without relying on platform-specific separators. ``BASE_DIR`` is resolved
from the current working directory's parent, so run the monitor from the
project directory (or set the working directory explicitly) when using these
constants.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Project output and data locations. These are intentionally defined once so
# callers do not duplicate path-building logic.
BASE_DIR = Path(__file__).resolve().parent.parent.parent
RAW_DIR = BASE_DIR / "data" / "raw"
UPLOAD_DIR = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
FINAL_DIR = BASE_DIR / "data" / "final"
TRACE_DIR = FINAL_DIR / "traces"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
LOG_DIR = BASE_DIR / "logs"

# Target endpoints used by the browser checks.
BASE_URL = "https://www.saucedemo.com"
LOGIN_URL = "https://www.saucedemo.com"
INVENTORY_URL = "https://www.saucedemo.com/inventory.html"


DEFAULT_TIMEOUT_MS = 20_000  # Playwright timeout in milliseconds (20 seconds)


@dataclass
class Auth:
    """Credentials and browser state settings for the test portal.

    Each credential defaults to the value of its matching environment
    variable. The ``"None"`` fallback preserves the existing behavior but is
    not a valid credential; configure the variables before running checks.
    """

    standard_user: str = os.getenv("STANDARD_USERNAME", "None")
    locked_out_user: str = os.getenv("LOCKED_OUT_USERNAME", "None")
    problem_user: str = os.getenv("PROBLEM_USERNAME", "None")
    performance_glitch_user: str = os.getenv("PERFORMANCE_GLITCH_USERNAME", "None")
    password: str = os.getenv("STANDARD_PASSWORD", "None")
    session_storage_dir: str = os.getenv("STATE_DIR", "None")
    session_state_filename: str = os.getenv("STATE_FILENAME", "None")
    session_user: str = ""

    def state_file(self) -> Path:
        """Return the browser state path relative to :data:`BASE_DIR`."""
        return (
            Path(self.session_storage_dir)
            / f"{self.session_state_filename}_{self.session_user}.json"
        )


@dataclass
class Url:
    """URLs used by the authentication and inventory checks."""

    base_url: str = BASE_URL
    login_url: str = LOGIN_URL
    inventory_url: str = INVENTORY_URL


@dataclass
class PortalConfig:
    """Runtime options for a portal monitoring session.

    ``auth`` and ``url`` are required so a caller must provide the portal
    credentials and endpoints explicitly. ``default_timeout_ms`` is passed to
    Playwright and is expressed in milliseconds.
    """

    auth: Auth
    url: Url
    headless: bool = True
    max_retries: int = 3
    backoff_base: float = 1.5
    force_relogin: bool = False
    default_timeout_ms: int = DEFAULT_TIMEOUT_MS
    log_dir: Path = LOG_DIR

    # the actual value that will be used by Playwright
    timeout_ms: int = field(init=False)

    def __post_init__(self):
        # Will be overwritten right after the creation if a CLI value is supplied
        self.timeout_ms = self.default_timeout_ms

    @property
    def timeout(self) -> dict[str, int]:
        """Named timeout preset in milliseconds"""
        return {
            "10s": 10_000,
            "20s": self.default_timeout_ms,
            "15s": 15_000,
            "25s": 25_000,
            "30s": 30_000,
        }

    def resolve_timeout(self, key: str | int | None = None) -> int:
        """Resolve a timeout key (or raw ms) to an integer milliseconds value"""
        if key is None:
            return self.default_timeout_ms
        if isinstance(key, int):
            return key
        # string keys
        try:
            return self.timeout[key]
        except KeyError:
            raise ValueError(
                f"Unknown timeout key {key!r}. Valid keys: {list(self.timeout)}"
            ) from None


def ensure_project_directories(config: "PortalConfig") -> None:
    """A fresh clone or CI runner starts with none of these folders —
    only the code creating them explicitly can be trusted."""
    for directory in (LOG_DIR, SCREENSHOT_DIR, FINAL_DIR, TRACE_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    config.auth.state_file().parent.mkdir(parents=True, exist_ok=True)
