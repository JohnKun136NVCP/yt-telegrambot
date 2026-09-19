"""Shared logging helpers.

Every module used to repeat the same ~15 lines to create its own log file.
This helper does it once and also makes sure the ``logs/`` directory exists
(a missing directory used to crash the bot at import time).
"""

import logging
from pathlib import Path

LOG_DIR = Path("logs")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def get_file_logger(
    name: str,
    filename: str,
    level: int = logging.INFO,
) -> logging.Logger:
    """Return a logger that writes to ``logs/<filename>``.

    Calling it several times for the same logger never adds duplicate handlers.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger(name)

    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        logger.setLevel(level)
        handler = logging.FileHandler(LOG_DIR / filename, encoding="utf-8")
        handler.setFormatter(logging.Formatter(LOG_FORMAT))
        logger.addHandler(handler)

    return logger