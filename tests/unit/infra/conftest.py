import pytest
import rok_assistant.infra.logger as logger_module


@pytest.fixture(autouse=True)
def _reset_logger_state():
    """Reset logger initialization state between tests."""
    logger_module._initialized = False
    yield
    logger_module._initialized = False
