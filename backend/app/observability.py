"""How every process says what it is doing.

Five processes write to the same journal on one VM, so a line has to say which
one wrote it, and a line has to survive being parsed. The format this replaces
was a JSON-shaped string built by `%`-substitution, which meant a message
containing a quote -- a filename, a pip error, anything a person typed --
produced a line no JSON parser would accept. Logs are read on the worst day of
a deployment's life, and that is the day a stack trace has quotes in it.

Only the standard library. A structured-logging dependency would buy field
binding this does not need and one more thing to keep current.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

# Anything the application deliberately attaches to a record. `logging` puts
# every argument of `logger.info(..., extra={...})` straight onto the record,
# so the allowed set is named here rather than guessed by filtering out the
# built-ins -- a filter would leak whatever a future version of `logging`
# adds.
CONTEXT = ("request_id", "run_id", "task_id", "worker_id", "schedule_id")


class JsonFormatter(logging.Formatter):
    """One line, one object, always parseable."""

    def __init__(self, process: str) -> None:
        super().__init__()
        self.process = process

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "process": self.process,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for name in CONTEXT:
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = str(value)
        if record.exc_info:
            # In the line rather than after it: a traceback written as
            # following lines is a traceback that arrives detached from the
            # message once anything collects the journal.
            payload["error"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


# Loggers that install handlers of their own and refuse to propagate.
# Uvicorn's are the ones that matter: without this, half of the API's output
# is JSON and the other half is `INFO:     127.0.0.1 - "GET ..."`, and the
# half that is not JSON is the request log.
ADOPTED = ("uvicorn", "uvicorn.error", "uvicorn.access")


def configure_logging(process: str, *, level: int = logging.INFO) -> None:
    """Send `process`'s logs to stdout as JSON.

    Replaces existing handlers rather than adding to them, so calling this
    after something else (uvicorn, a test harness) configured logging leaves
    one line per event instead of two.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(process))
    root = logging.getLogger()
    for existing in list(root.handlers):
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    for name in ADOPTED:
        adopted = logging.getLogger(name)
        adopted.handlers.clear()
        adopted.propagate = True
