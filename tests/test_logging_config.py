import logging
from datetime import date
from pathlib import Path

import pytest

from src.config import logging_config


def test_errors_go_to_separate_dated_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(logging_config, "LOG_DIR", tmp_path)
    logging_config.setup_logging(level="INFO")
    try:
        logger = logging_config.get_logger("test")
        logger.info("info-line")
        logger.error("error-line")
    finally:
        root = logging.getLogger()
        for handler in root.handlers[:]:
            handler.close()
            root.removeHandler(handler)

    stamp = f"{date.today():%Y%m%d}"
    app_log = (tmp_path / f"app_{stamp}.log").read_text(encoding="utf-8")
    error_log = (tmp_path / f"error_{stamp}.log").read_text(encoding="utf-8")
    assert "info-line" in app_log
    assert "error-line" in app_log
    assert "error-line" in error_log
    assert "info-line" not in error_log
    assert not list(tmp_path.glob("debug_*.log"))
