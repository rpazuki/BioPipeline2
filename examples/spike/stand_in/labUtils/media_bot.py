"""Parsing plate-reader exports. A stand-in; see the package docstring."""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Any

Table = list[dict[str, Any]]


def _read(path: str | Path) -> Table:
    with Path(path).open(newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _number(value: Any) -> float:
    return float(str(value).strip())


def parse(
    raw_data: str,
    meta_data: str,
    value_column_name: str = "od600",
    output_dir: str | None = None,
) -> Table:
    """Join a plate-reader export to its protocol metadata, by well.

    Takes **paths** and returns a live table: the first step of a stage reads
    from disk, and everything after it is handed the object. That is the shape
    the runner is built around, and the reason a stage is one container.
    """
    readings = _read(raw_data)
    metadata = {row["well"]: row for row in _read(meta_data)}

    joined: Table = []
    for row in readings:
        well = row["well"]
        record = {
            "well": well,
            "time_h": _number(row["time_h"]),
            value_column_name: _number(row[value_column_name]),
        }
        record.update({k: v for k, v in metadata.get(well, {}).items() if k != "well"})
        joined.append(record)

    if output_dir:
        # `output_dir` is injected by the runner into any callable that accepts
        # it, because the existing engine does the same and pipelines rely on
        # it. Writing here proves that injection works.
        Path(output_dir, "parsed_rows.txt").write_text(f"{len(joined)}\n")
    return joined


def replicate_stats(df: Table, ddof: int = 0) -> Table:
    """Collapse replicate wells into one series per group."""
    groups: dict[tuple[str, float], list[float]] = {}
    for row in df:
        key = (str(row.get("group_id", row["well"])), row["time_h"])
        groups.setdefault(key, []).append(row["od600"])

    collapsed: Table = []
    for (group, time_h), values in sorted(groups.items()):
        collapsed.append(
            {
                "well": group,
                "group_id": group,
                "time_h": time_h,
                "od600": statistics.fmean(values),
                "od600_sd": statistics.pstdev(values)
                if ddof == 0
                else statistics.stdev(values),
                "n": len(values),
            }
        )
    return collapsed
