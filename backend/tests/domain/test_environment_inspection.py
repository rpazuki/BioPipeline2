"""Inspect public Python call targets and report module import failures."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.infrastructure.environments import INTROSPECT, BuildFailed, GenerationBuilder, introspect


@pytest.mark.parametrize("explicit_exports", [False, True])
def test_inspection_includes_reexported_functions(tmp_path, explicit_exports):
    package = tmp_path / "example_package"
    package.mkdir()
    (package / "implementation.py").write_text(
        'def calculate(value, scale=2):\n    """Scale a value."""\n    return value * scale\n'
    )
    source = "from .implementation import calculate\nfrom math import sqrt as _private\n"
    if explicit_exports:
        source += '__all__ = ["calculate"]\n'
    (package / "__init__.py").write_text(source)

    result = subprocess.run(
        [sys.executable, "-c", INTROSPECT, "example_package"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )

    found = json.loads(result.stdout)
    assert found["callables"] == [
        {"name": "calculate", "signature": "(value, scale=2)", "summary": "Scale a value."}
    ]


def test_inspection_error_includes_underlying_import_error():
    builder = Mock(spec=GenerationBuilder)
    error = "ValueError: numpy.dtype size changed, may indicate binary incompatibility"
    builder._run.return_value = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr=f"Traceback:\n{error}\n"
    )

    with pytest.raises(BuildFailed) as caught:
        introspect(builder, Path("/example/environment"), "pandas")

    assert error in caught.value.message
    assert error in caught.value.log
