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


def make_table(rows: int = 3) -> list[dict[str, int]]:
    """Stands in for a function returning a DataFrame: a live object that has
    no meaningful round-trip through a file."""
    return [{"n": index} for index in range(rows)]


def count_rows(table: list[dict[str, int]]) -> int:
    """Receives the object itself, not a path or a name."""
    if not isinstance(table, list):
        raise TypeError(f"expected the table object, received {type(table).__name__}")
    return len(table)


def write_table(path: str, rows: int = 3) -> str:
    """A step that spills to disk and returns the path.

    This is how a stage handling data too large to hold in memory is written:
    the next step takes the path and opens it.
    """
    from pathlib import Path

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(str(index) for index in range(rows)))
    return str(target)


def count_lines(path: str) -> int:
    """Receives the path a previous step returned."""
    from pathlib import Path

    return len(Path(path).read_text().splitlines())


def write_marker(output_dir: str) -> str:
    """Writes into whatever `output_dir` the runner injected.

    Stands in for a science function that takes `output_dir` — the shape the
    existing engine established and real pipelines rely on.
    """
    from pathlib import Path

    marker = Path(output_dir) / "marker.txt"
    marker.write_text("written\n")
    return str(marker)
