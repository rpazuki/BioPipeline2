"""Fitting growth curves. A stand-in; see the package docstring."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

Table = list[dict[str, Any]]


def transform_to_log_n_n0(
    df: Table,
    value_col: str = "od600",
    transformed_col: str = "log_od_od0",
    # The lab's own argument name, kept verbatim: a stand-in whose signature
    # differs from the real one proves nothing about the real one.
    OD_0_averaging_window: int = 4,
) -> Table:
    """log(N / N0), with N0 averaged over the first few time points."""
    by_well: dict[str, list[dict[str, Any]]] = {}
    for row in df:
        by_well.setdefault(row["well"], []).append(row)

    out: Table = []
    for well, rows in sorted(by_well.items()):
        ordered = sorted(rows, key=lambda row: row["time_h"])
        window = [row[value_col] for row in ordered[:OD_0_averaging_window]]
        baseline = sum(window) / len(window) if window else 1.0
        for row in ordered:
            value = row[value_col]
            out.append(
                {
                    **row,
                    "well": well,
                    transformed_col: math.log(value / baseline)
                    if baseline > 0 and value > 0
                    else 0.0,
                }
            )
    return out


def fit_max_growth_rate(
    df: Table,
    time_col: str = "time_h",
    value_col: str = "log_od_od0",
    moving_window_size: int = 5,
    smoothing_iterations: int = 1,
    output_dir: str | None = None,
) -> dict[str, float]:
    """Steepest slope over a moving window, per well.

    Returns a mapping of scalars, which is what the runner turns into a task's
    metrics — so this is also the step that proves metrics come back.
    """
    by_well: dict[str, list[dict[str, Any]]] = {}
    for row in df:
        by_well.setdefault(row["well"], []).append(row)

    rates: dict[str, float] = {}
    for well, rows in by_well.items():
        ordered = sorted(rows, key=lambda row: row[time_col])
        best = 0.0
        for start in range(max(1, len(ordered) - moving_window_size + 1)):
            window = ordered[start : start + moving_window_size]
            if len(window) < 2:
                continue
            span = window[-1][time_col] - window[0][time_col]
            if span <= 0:
                continue
            best = max(best, (window[-1][value_col] - window[0][value_col]) / span)
        rates[f"mu_max_{well}"] = round(best, 6)

    if output_dir:
        lines = "\n".join(f"{well},{rate}" for well, rate in sorted(rates.items()))
        Path(output_dir, "growth_rates.csv").write_text(f"well,mu_max\n{lines}\n")
    return rates
