"""A pipeline that imports components must compile through the API.

This is the case the API could not handle at all: `create_revision` accepted a
`load_library` argument, `DirectoryLibraryLoader` existed and was tested, and
no route ever put the two together. Every document with a `uses:` answered
`component.no_loader` -- which is most of the real ones, since pervasive reuse
is the reason ADR 0026 kept components.

The fixture is `examples/pipelines/od600_growth_rates.yaml`: a real shape, with
a matrix whose rows select a different component graph.
"""

from __future__ import annotations

import pathlib
import uuid

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.db

ROOT = pathlib.Path(__file__).resolve().parents[3]
EXAMPLE = ROOT / "examples/pipelines/od600_growth_rates.yaml"


@pytest.fixture
def document() -> str:
    """The example, renamed per test: revisions are immutable and versioned
    per pipeline, so a shared name makes version assertions order-dependent."""
    text = EXAMPLE.read_text()
    return text.replace("pipeline: od600_growth_rates", f"pipeline: od600_{uuid.uuid4().hex[:8]}")


def test_a_component_using_pipeline_previews(as_admin: TestClient, document: str):
    response = as_admin.post("/api/v1/pipelines/compile-preview", json={"source_text": document})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True, body["diagnostics"]


def test_the_matrix_expands_into_one_stage_per_row(as_admin: TestClient, document: str):
    """Both graphs the matrix can select are pinned, not just the one a given
    row picks."""
    body = as_admin.post("/api/v1/pipelines/compile-preview", json={"source_text": document}).json()
    assert [stage["key"] for stage in body["stages"]] == ["fit:no_replicates", "fit:replicates"]


def test_the_component_steps_are_expanded_into_the_graph(as_admin: TestClient, document: str):
    """Expanded, not referenced: the IR has to stay self-contained, or a
    revision stops meaning one thing forever."""
    body = as_admin.post("/api/v1/pipelines/compile-preview", json={"source_text": document}).json()
    steps = {stage["key"]: stage["steps"] for stage in body["stages"]}
    assert steps["fit:no_replicates"] == [
        "df_parsed",
        "df_transformed",
        "df_fit_max_growth_rate",
    ]
    # The other matrix row selects a different graph, with a different shape.
    assert steps["fit:replicates"] == [
        "df_parsed",
        "df_replicate_stats",
        "df_transformed",
        "df_fit_max_growth_rate",
    ]


def test_the_public_inputs_reach_the_contract(as_admin: TestClient, document: str):
    body = as_admin.post("/api/v1/pipelines/compile-preview", json={"source_text": document}).json()
    declared = {item["key"]: item for item in body["inputs"]}
    assert set(declared) == {"data_root", "mapping_yaml"}
    assert declared["data_root"]["accept"] == "directory"
    assert declared["mapping_yaml"]["accept"] == "file"


def test_a_component_using_pipeline_becomes_a_revision(as_admin: TestClient, document: str):
    response = as_admin.post("/api/v1/pipelines/revisions", json={"source_text": document})
    assert response.status_code == 201, response.text
    revision = response.json()["revision_id"]

    contract = as_admin.get(f"/api/v1/pipelines/revisions/{revision}").json()
    assert {item["key"] for item in contract["inputs"]} == {"data_root", "mapping_yaml"}
    # One `results` per matrix row, not one in total: each row writes to its
    # own path (`processed/{variant.name}/...`), so they are different outputs
    # that happen to share a key. The stage is what tells them apart.
    assert [output["key"] for output in contract["outputs"]] == ["results", "results"]
    assert {output["stage"] for output in contract["outputs"]} == {
        "fit:no_replicates",
        "fit:replicates",
    }
    assert len({output["path"] for output in contract["outputs"]}) == 2


def test_a_library_outside_the_root_is_refused(as_admin: TestClient, document: str):
    """The reference is text an author wrote, so escaping the root must be
    refused rather than read."""
    escaped = document.replace("library: growth_rates.yaml", "library: ../../etc/passwd")
    body = as_admin.post("/api/v1/pipelines/compile-preview", json={"source_text": escaped}).json()
    assert body["ok"] is False
    assert any("outside" in d["message"] for d in body["diagnostics"]), body["diagnostics"]


def test_a_missing_library_is_a_diagnostic_not_a_crash(as_admin: TestClient, document: str):
    missing = document.replace("library: growth_rates.yaml", "library: nope.yaml")
    response = as_admin.post("/api/v1/pipelines/compile-preview", json={"source_text": missing})
    assert response.status_code == 200
    assert response.json()["ok"] is False
