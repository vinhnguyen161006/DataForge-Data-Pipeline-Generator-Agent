import json
import logging
import sys
from datetime import UTC, datetime
from typing import Literal

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

HANDLER_NAME = "dataforge"
SERVER_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")
RESERVED_RECORD_FIELDS = frozenset(
    vars(logging.LogRecord("", logging.NOTSET, "", 0, "", None, None))
) | {"message", "asctime", "color_message"}


class JsonFormatter(logging.Formatter):
    """Render a record as one JSON line; fields passed through `extra=` become top-level keys."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(
            (key, value) for key, value in vars(record).items() if key not in RESERVED_RECORD_FIELDS
        )
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)
        return json.dumps(payload, default=str)


def configure_logging(level: LogLevel = "INFO") -> None:
    """Send JSON lines to stdout for the API, worker and publisher processes.

    Idempotent: replaces only the handler installed by a previous call, so handlers added by
    other tools (for example pytest) survive. Uvicorn loggers are routed through the root logger
    so server and application logs share one format.
    """
    root = logging.getLogger()
    for handler in [h for h in root.handlers if h.get_name() == HANDLER_NAME]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)
    for name in SERVER_LOGGERS:
        server_logger = logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
