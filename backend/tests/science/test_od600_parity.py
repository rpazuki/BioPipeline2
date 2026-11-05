"""Compare migrated tasks with the original processing graphs using real scientific code."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from app.domain.compiler import compile_pipeline
from app.domain.materialise import materialise
from app.infrastructure.pipeline_loader import DirectoryLibraryLoader, parse_document

pytestmark = pytest.mark.slow
ROOT = Path(__file__).resolve().parents[3]
BUNDLE = ROOT / "examples/migrations/od600"


@pytest.mark.parametrize("multiple", [False, True])
@pytest.mark.parametrize("method", ["no_replicates", "replicates", "post_replicates"])
def test_migrated_outputs_match_original_calls_with_real_library(tmp_path, multiple, method):
    generation = os.environ.get("BP_TEST_OD600_GENERATION")
    library = os.environ.get("BP_TEST_OD600_LIBRARY")
    if not generation or not library:
        pytest.skip(
            "Set BP_TEST_OD600_GENERATION and BP_TEST_OD600_LIBRARY for scientific parity checks."
        )
    name = "Multiple_OD600_growth_rates_ingestion" if multiple else "OD600_growth_rates_ingestion"
    compiled = compile_pipeline(
        parse_document((BUNDLE / "pipelines" / f"{name}.yaml").read_text()),
        load_library=DirectoryLibraryLoader(BUNDLE / "components"),
    ).pipeline
    assert compiled is not None
    fixtures = ROOT / "backend/tests/fixtures/od600"
    for reference in ("measurements.csv", "metadata.csv"):
        shutil.copyfile(fixtures / reference, tmp_path / reference)
    values = {
        "method": method,
        "od600_col": "od600",
        "strain_pattern": r"(\w+)",
        "custom_rules": {"WT": {"direction": "alphabetical", "sample_size": 2}},
        "moving_window_size": 5,
        "smoothing_iterations": 4,
        "smooth_window_size": 2,
        "minimum_fit_points": 5,
        "save_plot_data": True,
        **(
            {"data_root": "/work", "data_to_metadata_mapping_yaml": "/work/mapping.yaml"}
            if multiple
            else {"raw_file": "/work/measurements.csv", "metadata_file": "/work/metadata.csv"}
        ),
    }
    plan = materialise(
        compiled,
        values,
        enumerate_fanout=lambda _: [
            {"raw": "measurements.csv", "meta": "metadata.csv", "stem": "experiment1"},
            {"raw": "measurements.csv", "meta": "metadata.csv", "stem": "experiment2"},
        ],
    )
    assert plan.ok and len(plan.tasks) == (2 if multiple else 1)
    tasks = []
    for task in plan.tasks:
        tasks.append(
            {
                "steps": [
                    {
                        "name": step["name"],
                        "parameters": step["parameters"],
                        "retain": step["retain"],
                        "callable_ref": {
                            "kind": "python_callable",
                            "module": step["package"],
                            "attribute": step["method"],
                        },
                    }
                    for step in task.steps
                ],
                "inputs": [
                    {"key": key, "kind": "value", "value": value}
                    for key, value in task.inputs.items()
                ],
                "outputs": task.outputs,
            }
        )
    (tmp_path / "check.json").write_text(
        json.dumps(
            {
                "tasks": tasks,
                "graph": compiled.stages[
                    ["no_replicates", "replicates", "post_replicates"].index(method)
                ].component.graph,
                "values": values,
                "original": yaml.safe_load((fixtures / "legacy_component.yaml").read_text()),
            }
        )
    )
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "--read-only",
        "--cpus",
        "2",
        "--memory",
        "2g",
        "--pids-limit",
        "256",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--tmpfs",
        "/tmp:rw,mode=1777",
        "-v",
        f"{ROOT}:/repo:ro",
        "-v",
        f"{tmp_path}:/work:rw",
        "-v",
        f"{generation}:/env:ro",
        "-v",
        f"{library}:/lab:ro",
        "-e",
        "PYTHONPATH=/repo/backend:/env/lib/python3.12/site-packages:/lab",
        "-e",
        "MPLBACKEND=Agg",
        "-e",
        "MPLCONFIGDIR=/tmp/matplotlib",
        "-e",
        "OPENBLAS_NUM_THREADS=1",
        "-e",
        "OMP_NUM_THREADS=1",
        os.environ.get("BP_TEST_OD600_IMAGE", "biopipeline2/task-base:1.0"),
        "python",
        "/repo/backend/tests/science/od600_reference.py",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "all tables and plots match" in result.stdout
