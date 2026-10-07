import json
import logging
import sys
from collections.abc import Iterator

import pytest

from app.core.logging import HANDLER_NAME, JsonFormatter, configure_logging


def make_record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord("app.test", logging.INFO, __file__, 1, "run %s", ("r1",), None)
    record.__dict__.update(extra)
    return record


@pytest.fixture
def root_logger() -> Iterator[logging.Logger]:
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield root
    root.handlers, root.level = handlers, level


def test_formatter_emits_message_and_extra_fields() -> None:
    line = json.loads(JsonFormatter().format(make_record(run_id="r1", color_message="x")))
    assert line["level"] == "INFO"
    assert line["logger"] == "app.test"
    assert line["message"] == "run r1"
    assert line["run_id"] == "r1"
    assert "color_message" not in line
    assert "args" not in line


def test_formatter_includes_exception() -> None:
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            "app.test", logging.ERROR, __file__, 1, "failed", None, sys.exc_info()
        )
    line = json.loads(JsonFormatter().format(record))
    assert "ValueError: boom" in line["exception"]


def test_configure_logging_is_idempotent_and_keeps_foreign_handlers(
    root_logger: logging.Logger,
) -> None:
    foreign = logging.NullHandler()
    root_logger.addHandler(foreign)
    configure_logging("DEBUG")
    configure_logging("WARNING")
    own = [h for h in root_logger.handlers if h.get_name() == HANDLER_NAME]
    assert len(own) == 1
    assert foreign in root_logger.handlers
    assert root_logger.level == logging.WARNING
    assert logging.getLogger("uvicorn.access").propagate
