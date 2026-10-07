import logging
import os
import sys
from datetime import date
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(funcName)s:%(lineno)d - %(message)s"


class DailyFileHandler(logging.FileHandler):
    """Write to <name>_YYYYMMDD.log and switch to a new file when the date changes."""

    def __init__(self, name: str, level: int) -> None:
        self._name = name
        self._date = date.today()
        super().__init__(self._path(), encoding="utf-8")
        self.setLevel(level)

    def _path(self) -> str:
        return str(LOG_DIR / f"{self._name}_{self._date:%Y%m%d}.log")

    def emit(self, record: logging.LogRecord) -> None:
        if date.today() != self._date:
            self._date = date.today()
            self.close()  # the stream is reopened lazily on the next emit
            self.baseFilename = os.path.abspath(self._path())
        super().emit(record)


def setup_logging(level: str = "INFO", log_to_file: bool = True) -> None:
    """Configure the root logger: console always; daily files app / error (and debug)."""
    numeric_level = logging.getLevelNamesMapping().get(level.upper(), logging.INFO)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_to_file:
        LOG_DIR.mkdir(exist_ok=True)
        handlers.append(DailyFileHandler("app", logging.INFO))
        handlers.append(DailyFileHandler("error", logging.ERROR))
        if numeric_level <= logging.DEBUG:
            handlers.append(DailyFileHandler("debug", logging.DEBUG))
    logging.basicConfig(level=numeric_level, format=LOG_FORMAT, handlers=handlers, force=True)
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a logger; usually called as get_logger(__name__)."""
    return logging.getLogger(name)
