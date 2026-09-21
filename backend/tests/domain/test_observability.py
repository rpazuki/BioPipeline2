"""Log lines that survive being parsed.

Logs are read on the worst day of a deployment's life, and that is the day a
message has quotes in it.
"""

from __future__ import annotations

import json
import logging

from app.observability import JsonFormatter, configure_logging


def record(message: str, *args: object, **extra: object) -> logging.LogRecord:
    made = logging.LogRecord(
        name="biopipeline2.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=args,
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(made, key, value)
    return made


def test_a_message_with_quotes_in_it_is_still_one_json_object():
    """The format this replaced built JSON by substitution, so a pip error or
    a filename with a quote in it produced a line nothing could parse."""
    line = JsonFormatter("worker").format(record('could not find "labUtils": {"code": 1}'))

    parsed = json.loads(line)
    assert parsed["message"] == 'could not find "labUtils": {"code": 1}'
    assert parsed["process"] == "worker"
    assert parsed["level"] == "INFO"


def test_context_is_a_field_rather_than_a_sentence():
    """A field survives a grep that a sentence does not."""
    line = JsonFormatter("api").format(record("request failed", request_id="req_abc"))

    assert json.loads(line)["request_id"] == "req_abc"


def test_anything_not_deliberately_attached_stays_out():
    line = JsonFormatter("api").format(record("hello", secret="do not log me"))

    assert "secret" not in json.loads(line)


def test_a_traceback_travels_in_the_line_it_belongs_to():
    try:
        raise ValueError('the "wrong" thing')
    except ValueError:
        made = record("promotion failed")
        made.exc_info = __import__("sys").exc_info()
        line = JsonFormatter("worker").format(made)

    parsed = json.loads(line)
    assert "ValueError" in parsed["error"]
    assert parsed["message"] == "promotion failed"


def test_configuring_twice_does_not_double_every_line():
    """Uvicorn and a test harness both configure logging; two handlers means
    two of every line, which is how a journal becomes unreadable."""
    configure_logging("api")
    configure_logging("api")

    assert len(logging.getLogger().handlers) == 1


def test_uvicorns_own_lines_are_adopted():
    """Otherwise half the API's output is JSON and the other half is the
    request log, which is the half an incident needs."""
    access = logging.getLogger("uvicorn.access")
    access.addHandler(logging.NullHandler())
    access.propagate = False

    configure_logging("api")

    assert access.handlers == []
    assert access.propagate is True
