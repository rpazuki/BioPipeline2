"""Workspace layout, path containment, and output collection."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.workspace import (
    WorkspaceError,
    checksum,
    collect_outputs,
    create_workspace,
    destroy_workspace,
)


@pytest.fixture
def workspace(tmp_path):
    return create_workspace(tmp_path, uuid.uuid4())


def test_the_layout_is_created(workspace):
    for directory in (workspace.platform, workspace.inputs, workspace.outputs, workspace.logs):
        assert directory.is_dir()


def test_the_path_is_generated_from_the_run_id_not_from_user_input(workspace):
    """Two runs cannot collide, and a crafted name cannot steer the path."""
    assert workspace.root.name == str(workspace.run_id)


def test_an_ordinary_relative_path_resolves(workspace):
    assert workspace.resolve("outputs/report.html").parent == workspace.outputs


@pytest.mark.parametrize("path", ["/etc/passwd", "../escape", "outputs/../../escape", ".."])
def test_a_path_that_escapes_the_workspace_is_refused(workspace, path):
    with pytest.raises(WorkspaceError):
        workspace.resolve(path)


def test_an_empty_path_is_refused(workspace):
    with pytest.raises(WorkspaceError, match="must not be empty"):
        workspace.resolve("")


def test_a_symlink_pointing_outward_is_refused(workspace, tmp_path):
    """Containment is checked after resolution, so a link that looks contained
    but points outward is still caught."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace.inputs / "link").symlink_to(outside)
    with pytest.raises(WorkspaceError, match="outside the workspace"):
        workspace.resolve("inputs/link/secret")


def test_total_bytes_counts_files(workspace):
    (workspace.outputs / "a.txt").write_text("x" * 100)
    (workspace.outputs / "b.txt").write_text("y" * 50)
    assert workspace.total_bytes() == 150


def test_destroying_a_workspace_is_idempotent(workspace):
    destroy_workspace(workspace)
    assert not workspace.root.exists()
    destroy_workspace(workspace)  # the janitor may race with a worker


def test_checksums_are_stable(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"hello")
    assert checksum(path) == checksum(path)
    assert len(checksum(path)) == 64


# --- collecting outputs ---------------------------------------------------


def test_a_produced_file_is_collected_with_its_checksum(workspace):
    (workspace.outputs / "r.txt").write_text("data")
    collected, missing = collect_outputs(workspace, [{"key": "r", "path": "outputs/r.txt"}])
    assert not missing
    assert collected[0].size_bytes == 4
    assert collected[0].checksum_sha256 is not None


def test_a_produced_directory_is_collected_by_total_size(workspace):
    directory = workspace.outputs / "many"
    directory.mkdir()
    (directory / "a").write_text("xx")
    (directory / "b").write_text("yyy")
    collected, missing = collect_outputs(workspace, [{"key": "many", "path": "outputs/many"}])
    assert not missing
    assert collected[0].is_directory and collected[0].size_bytes == 5


def test_a_missing_required_output_is_reported(workspace):
    """A task that exits 0 without producing what it declared has failed, and
    only the filesystem can settle that."""
    collected, missing = collect_outputs(workspace, [{"key": "gone", "path": "outputs/gone.txt"}])
    assert missing == ["gone"] and not collected


def test_a_missing_optional_output_is_not_an_error(workspace):
    _, missing = collect_outputs(
        workspace, [{"key": "extra", "path": "outputs/x", "optional": True}]
    )
    assert not missing


def test_an_output_path_that_escapes_is_treated_as_missing(workspace):
    """Never followed, whatever the task claimed."""
    _, missing = collect_outputs(workspace, [{"key": "evil", "path": "../../etc/passwd"}])
    assert missing == ["evil"]
