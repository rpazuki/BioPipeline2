"""Write tabular task results into the task's declared output directory."""

from pathlib import Path
from typing import Any


def as_path(value: str) -> Path:
    """Convert a staged input filename to a Path for path-aware processing functions."""
    return Path(value)


def write_csv(value: Any, filename: str, output_dir: str | Path) -> str:
    """Write a table as a comma-separated file and return its absolute path.

    The value must provide a callable ``to_csv`` method. The filename must
    remain inside the runner-supplied output directory; invalid paths raise
    ``ValueError`` and unsupported values raise ``TypeError``.
    """
    root = Path(output_dir).resolve()
    destination = (root / filename).resolve()
    if destination == root or not destination.is_relative_to(root):
        raise ValueError("The result filename must stay within the declared output directory.")
    writer = getattr(value, "to_csv", None)
    if not callable(writer):
        raise TypeError("The result must be a table with a to_csv method.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    writer(destination, index=False)
    return str(destination)
