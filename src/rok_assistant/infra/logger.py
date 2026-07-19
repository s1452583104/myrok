import logging
import sys
from pathlib import Path
from datetime import datetime

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_initialized = False

def setup_logging(log_dir: Path, level: str = "INFO") -> None:
    global _initialized
    if _initialized:
        return
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"rok_assistant_{datetime.now():%Y%m%d_%H%M%S}.log"
    root = logging.getLogger()
    root.setLevel(level)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(console)
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
    root.addHandler(file_handler)
    _initialized = True

def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
