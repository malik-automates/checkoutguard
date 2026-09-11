"""
src/core/logger.py  -> LOGGING SETUP
—————————————————————————————————————
Rule: Use logging, NOT print(). Logging gives you timestamps, severity levels, and can be turned on/off without editing code. Clients see professionalism.
"""

import logging
import logging.handlers
import sys
from pathlib import Path


def setup_logging(log_dir: Path, level: str = "INFO") -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("checkguard")
    # GUARD: if this logger already has handlers, DON'T attach more.
    # Without this, every extra call to setup_logging() doubles your
    # output permanently — this is the #1 cause of duplicate logs in Python.
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(getattr(logging, level.upper(), logging.INFO))
    console.setFormatter(fmt)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "pipeline.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(fmt)

    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.propagate = False  # don't also bubble up to the root logger's handlers

    return logger
