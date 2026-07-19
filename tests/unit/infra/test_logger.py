import logging
from pathlib import Path
from rok_assistant.infra.logger import setup_logging, get_logger

def test_get_logger_returns_named_logger(tmp_path):
    setup_logging(log_dir=tmp_path, level="INFO")
    log = get_logger("test.module")
    assert log.name == "test.module"
    assert log.level <= logging.INFO

def test_setup_logging_creates_log_dir(tmp_path):
    log_dir = tmp_path / "logs"
    setup_logging(log_dir=log_dir, level="INFO")
    assert log_dir.exists()
