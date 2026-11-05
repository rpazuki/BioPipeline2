"""Compare native runner outputs with the original component's direct function calls."""

import importlib
import inspect
import json
import re
from pathlib import Path

import pandas as pd

from app.runner.main import run


def resolve(value, payload):
    """Resolve the original engine's references to earlier results."""
    if isinstance(value, dict):
        return {key: resolve(item, payload) for key, item in value.items()}
    if isinstance(value, list):
        return [resolve(item, payload) for item in value]
    return payload[value] if isinstance(value, str) and value in payload else value


def main():
    """Run the original calls and compare every declared table and generated plot."""
    work = Path("/work")
    check = json.loads((work / "check.json").read_text())
    original = check["original"]
    graph = next(
        entry[check["graph"]] for entry in original["pipelines"] if check["graph"] in entry
    )
    module = importlib.import_module("labUtils.media_bot")
    payload = {
        "raw_data": module.parse_raw_CLARIOstar_export(
            work / "measurements.csv", value_column_name="od600"
        ),
        "meta_data": module.parse_protocol_metadata(work / "metadata.csv"),
    }
    reference = work / "reference"
    reference.mkdir()
    for entry in graph["Processes"]:
        name, spec = next(iter(entry.items()))
        target = getattr(importlib.import_module(spec["package"]), spec["method"])
        arguments = resolve(spec["parameters"], payload)
        # The old default lacks the capture group required by pandas.str.extract.
        # Apply the same explicit correction used by the migrated publication.
        pattern = arguments.get("strain_pattern")
        if isinstance(pattern, str) and not re.compile(pattern).groups:
            arguments["strain_pattern"] = f"({pattern})"
        if "output_dir" in inspect.signature(target).parameters:
            arguments["output_dir"] = reference
        payload[name] = target(**arguments)
    filenames = []
    for entry in graph["Outputs"]:
        name, filename = next(iter(entry.items()))
        payload[name].to_csv(reference / filename, index=False)
        filenames.append(filename)
    expected_plots = {path.name for path in (reference / "plots").glob("*")}
    assert expected_plots, "The reference must actually produce plots."
    for task in check["tasks"]:
        workspace = work / "native"
        workspace.mkdir(exist_ok=True)
        result = run(task, workspace)
        assert result["status"] == "succeeded", result
        actual = workspace / task["outputs"][0]["path"]
        for filename in filenames:
            if (reference / filename).stat().st_size < 2:
                assert (actual / filename).read_bytes() == (reference / filename).read_bytes()
            else:
                pd.testing.assert_frame_equal(
                    pd.read_csv(actual / filename),
                    pd.read_csv(reference / filename),
                    check_exact=False,
                    rtol=1e-10,
                    atol=1e-12,
                )
        assert {path.name for path in (actual / "plots").glob("*")} == expected_plots
        for filename in expected_plots:
            assert (actual / "plots" / filename).read_bytes() == (
                reference / "plots" / filename
            ).read_bytes()
    print(f"all tables and plots match: {len(check['tasks'])} tasks, {len(filenames)} tables each")


if __name__ == "__main__":
    main()
