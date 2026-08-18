"""Project logging that is safe for stdio MCP transports."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(name: str = "cloud_music_mcp") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.propagate = False

    if os.getenv("MCP_LOG_ENABLE", "false").lower() != "true":
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.CRITICAL + 1)
        return logger

    log_dir = _data_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "cloud-music-mcp.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


def _data_dir() -> Path:
    override = os.getenv("CLOUD_MUSIC_MCP_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32" and os.getenv("APPDATA"):
        return Path(os.environ["APPDATA"]) / "cloud-music-mcp"
    return Path.home() / ".cloud-music-mcp"
