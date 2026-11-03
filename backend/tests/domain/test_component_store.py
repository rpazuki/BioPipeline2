"""Preserve component sources, prevent lost edits, and contain file access."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.domain.errors import Conflict, NotFound, ValidationFailed
from app.infrastructure.component_store import ComponentStore, source_digest
from app.infrastructure.pipeline_loader import DirectoryLibraryLoader

SOURCE = """# Exact component source
graphs:
  convert:
    - name: result
      package: builtins
      method: str
      parameters:
        object: hello
"""


def test_saved_references_keep_their_original_calls(tmp_path):
    store = ComponentStore(tmp_path)
    first = store.save("convert.yaml", SOURCE, None)
    changed = SOURCE.replace("hello", "updated")
    second = store.save("convert.yaml", changed, first["digest"])
    assert store.read("convert.yaml")["source_text"] == changed
    assert store.read("convert.yaml")["reference"] == second["reference"]
    assert store.read("convert.yaml", first["digest"])["source_text"] == SOURCE
    loader = DirectoryLibraryLoader(tmp_path)
    assert loader(first["reference"]).graphs["convert"][0].parameters["object"] == "hello"
    assert loader(second["reference"]).graphs["convert"][0].parameters["object"] == "updated"
    assert len(store.revisions("convert.yaml")) == 2
    assert len(store.list()) == 1


def test_imported_libraries_are_visible_and_preserved_on_first_edit(tmp_path):
    path = tmp_path / "existing.yaml"
    path.write_text(SOURCE, encoding="utf-8")
    store = ComponentStore(tmp_path)
    assert store.list()[0]["name"] == "existing.yaml"
    store.save("existing.yaml", SOURCE + "# new comment\n", source_digest(SOURCE))
    assert store.read("existing.yaml", source_digest(SOURCE))["source_text"] == SOURCE


def test_same_source_is_not_duplicated_in_history(tmp_path):
    store = ComponentStore(tmp_path)
    saved = store.save("convert.yaml", SOURCE, None)
    assert store.save("convert.yaml", SOURCE, saved["digest"]) == saved
    assert len(store.revisions("convert.yaml")) == 1


def test_windows_line_endings_and_unicode_are_preserved(tmp_path):
    store = ComponentStore(tmp_path)
    source = SOURCE.replace("hello", "\u03b1").replace("\n", "\r\n")
    saved = store.save("windows.yaml", source, None)
    assert saved["source_text"] == source
    assert store.read("windows.yaml")["source_text"] == source


def test_legacy_processes_format_remains_supported(tmp_path):
    source = """pipelines:
  - convert:
      Processes:
        - result:
            package: builtins
            method: str
            parameters: {object: hello}
"""
    saved = ComponentStore(tmp_path).save("legacy.yaml", source, None)
    assert saved["graphs"] == ["convert"]
    assert saved["source_text"] == source


def test_two_editors_cannot_silently_overwrite_one_another(tmp_path):
    store = ComponentStore(tmp_path)
    saved = store.save("convert.yaml", SOURCE, None)

    def save(label):
        try:
            store.save("convert.yaml", SOURCE + f"# {label}\n", saved["digest"])
            return "saved"
        except Conflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ["first", "second"])) == ["conflict", "saved"]
    assert len(store.revisions("convert.yaml")) == 2


@pytest.mark.parametrize(
    "name",
    [
        "../outside.yaml",
        "/tmp/outside.yaml",
        "a/../b.yaml",
        ".revisions/test.yaml",
        "a\\b.yaml",
        "a//b.yaml",
    ],
)
def test_paths_cannot_escape_or_access_internal_history(tmp_path, name):
    with pytest.raises(ValidationFailed):
        ComponentStore(tmp_path).save(name, SOURCE, None)


def test_symlink_to_an_outside_directory_is_refused(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValidationFailed):
        ComponentStore(root).save("escape/component.yaml", SOURCE, None)
    assert not list(outside.iterdir())


def test_invalid_source_does_not_replace_the_current_library(tmp_path):
    store = ComponentStore(tmp_path)
    saved = store.save("convert.yaml", SOURCE, None)
    with pytest.raises(ValidationFailed):
        store.save("convert.yaml", "graphs: {empty: []}", saved["digest"])
    assert store.read("convert.yaml")["source_text"] == SOURCE


def test_invalid_existing_library_can_be_loaded_for_correction(tmp_path):
    (tmp_path / "broken.yaml").write_text("not a mapping", encoding="utf-8")
    row = ComponentStore(tmp_path).list()[0]
    assert row["error"]
    assert row["source_text"] == "not a mapping"


def test_unknown_revision_returns_not_found(tmp_path):
    with pytest.raises(NotFound):
        ComponentStore(tmp_path).read("missing.yaml")
