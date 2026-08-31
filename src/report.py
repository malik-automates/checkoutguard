from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CheckResult:
    """One structured result per account. Every field has a safe,
    correctly-typed default — no fragile tuple-indexing landmines."""

    username: str
    login_success: bool = False
    checkout_end_to_end: bool = False
    sorted_prices: list[float] = field(default_factory=list)
    is_sorted: bool = False
    order_receipt: Path | None = None
    social_link_tab: list[tuple[str, bool]] = field(default_factory=list)
    notes: str | None = None


@dataclass
class HealthCheckReport:
    """Mutable summary of one monitoring run.

    ``issues`` contains human-readable descriptions of problems encountered
    during the run. Counters are initialized to zero for each new report.
    """

    check: CheckResult
    run_timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    steps_attempted: int = 0
    steps_succeeded: int = 0
    steps_failed: int = 0
    issues: list = field(default_factory=list)

    def add_issue(self, description: str) -> None:
        """Append an issue description to the report."""
        self.issues.append(description)
