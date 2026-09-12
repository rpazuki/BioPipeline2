"""Callables the runner tests invoke by name, as a pipeline would."""

from __future__ import annotations


def returns_metrics() -> dict[str, object]:
    """Numeric returns become metrics; non-numeric ones are ignored."""
    return {"rows": 3, "seconds": 1.5, "label": "ignored", "ok": True}


def always_raises() -> None:
    raise RuntimeError("the science failed")


def writes_output(path: str, content: str = "result") -> dict[str, int]:
    """Writes a file, as a real science function would."""
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return {"bytes_written": len(content)}
