"""Extract supported annotated classes without running default factories."""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from app.domain.errors import ValidationFailed
from app.infrastructure.environments import GenerationBuilder
from app.infrastructure.type_inspection import TYPE_INSPECTION, extract_types


@pytest.mark.parametrize(
    "name", ["", "module.Type;id", "module.$(id)", "module.Type'", "module.Type\nother"]
)
def test_invalid_class_names_never_reach_the_container(name):
    builder = Mock(spec=GenerationBuilder)
    with pytest.raises(ValidationFailed):
        extract_types(builder, Path("/unused"), name)
    builder._run.assert_not_called()


def test_extracts_nested_dataclasses_collections_and_typed_dict_presence(tmp_path):
    (tmp_path / "configuration.py").write_text("""from dataclasses import dataclass, field
from typing import TypedDict, NotRequired, Literal
class Label(TypedDict):
    name: str
    note: NotRequired[str]
@dataclass
class Rule:
    window: int
    mode: Literal["fast", "careful"] = "careful"
@dataclass
class Options:
    rules: list[Rule]
    labels: dict[str, Label]
    optional: int | None = None
    generated: list[int] = field(default_factory=lambda: 1/0)
""")
    result = subprocess.run(
        [sys.executable, "-c", TYPE_INSPECTION, "configuration.Options"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=True,
    )
    extracted = json.loads(result.stdout)
    fields = extracted["definitions"]["Options"]["fields"]
    assert fields["rules"]["container"] == "list"
    assert fields["labels"]["container"] == "map"
    assert fields["optional"]["nullable"] is True
    assert extracted["definitions"]["Label"]["fields"]["note"]["required"] is False
    assert "default" not in fields["generated"]
    assert any("factory was not executed" in note for note in extracted["notes"])
