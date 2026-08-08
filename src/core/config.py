"""
src/core/config.py -> SCRIPT CONFIG SETUP
——————————————————————————————————————————

CONFIG: File paths defined ONCE at the top — never hardcode paths in functions.

pathlib.Path works on both Windows and Linux/Mac (unlike string paths)

"""

import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ============== PATHS ==========================
BASE_DIR = Path(".").parent.resolve()
RAW_DIR = BASE_DIR / "data" / "raw"
UPLOAD_DIR = BASE_DIR / "data" / "raw"
PROC_DIR = BASE_DIR / "data" / "processed"
FINAL_DIR = BASE_DIR / "data" / "final"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
LOG_DIR = BASE_DIR / "logs"

# ============= TARGET URL SETTINGS =============
BASE_URL = "https://www.saucedemo.com"
LOGIN_URL = "https://www.saucedemo.com"
INVENTORY_URL = "https://the-internet.herokuapp.com/inventory.html"


DEFAULT_TIMEOUT_MS = 10_000  # 10 seconds — generous, but never infinite


@dataclass
class Auth:
    standard_user: str = os.getenv("STANDARD_USERNAME", "None")
    locked_out_user: str = os.getenv("LOCKED_OUT_USERNAME", "None")
    problem_user: str = os.getenv("PROBLEM_USERNAME", "None")
    performance_glitch_user: str = os.getenv("PERFORMANCE_GLITCH_USERNAME", "None")
    password: str = os.getenv("STANDARD_PASSWORD", "None")
    session_storage_dir: str = os.getenv("STATE_DIR", "None")

    @property
    def state_filename(self) -> Path:
        return BASE_DIR / self.session_storage_dir


@dataclass
class Url:
    base_url: str = BASE_URL
    login_url: str = LOGIN_URL
    inventory_url: str = INVENTORY_URL


@dataclass
class RunReport:
    run_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    steps_attempted: int = 0
    steps_succeeded: int = 0
    steps_failed: int = 0
    issues: list = field(default_factory=list)

    def add_issues(self, description: str) -> None:
        self.issues.append(description)


@dataclass
class PortalConfig:
    auth: Auth
    url: Url
    headless: bool = True
    max_retries: int = 3
    backoff_base: float = 1.5
    force_relogin: bool = False
    default_timeout_ms: int = DEFAULT_TIMEOUT_MS
