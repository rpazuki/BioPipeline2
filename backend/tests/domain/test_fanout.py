"""Enumerating a fan-out source.

Nothing implemented `FanOutEnumerator` until this existed: the protocol was
declared, `materialise` accepted one, `submit_run` forwarded one, and the API
passed `None`. Every pipeline with a fan-out — which is the ordinary shape of
this work, one task per plate-reader export — was unsubmittable.
"""

from __future__ import annotations

import pytest
import yaml

from app.domain.ir import CompiledFanOut
from app.infrastructure.fanout import DirectoryFanOut, FanOutFailed


@pytest.fixture
def data(tmp_path):
    root = tmp_path / "lab"
    root.mkdir()
    for index in (1, 2, 3):
        (root / f"plate_{index:02d}.csv").write_text("well,time_h,od600\n")
        (root / f"plate_{index:02d}_meta.csv").write_text("well,group_id\n")
    return root


@pytest.fixture
def enumerate_in(tmp_path):
    return DirectoryFanOut(roots=(tmp_path,))


# --- mapping_file ----------------------------------------------------------


def test_a_mapping_file_pairs_raw_with_metadata(data, enumerate_in):
    mapping = data / "mapping.yaml"
    mapping.write_text(
        yaml.safe_dump({"plate_01.csv": "plate_01_meta.csv", "plate_02.csv": "plate_02_meta.csv"})
    )
    items = enumerate_in(CompiledFanOut(type="mapping_file", mapping=str(mapping)))
    assert items == [
        {"raw": "plate_01.csv", "meta": "plate_01_meta.csv", "stem": "plate_01"},
        {"raw": "plate_02.csv", "meta": "plate_02_meta.csv", "stem": "plate_02"},
    ]


def test_the_stem_names_the_task_and_its_output_directory(data, enumerate_in):
    mapping = data / "m.yaml"
    mapping.write_text(yaml.safe_dump({"plate_01.csv": "plate_01_meta.csv"}))
    assert enumerate_in(CompiledFanOut(type="mapping_file", mapping=str(mapping)))[0]["stem"] == (
        "plate_01"
    )


def test_an_empty_mapping_is_refused(data, enumerate_in):
    """A run with no tasks is not a run; saying so here names the file."""
    mapping = data / "m.yaml"
    mapping.write_text("{}\n")
    with pytest.raises(FanOutFailed):
        enumerate_in(CompiledFanOut(type="mapping_file", mapping=str(mapping)))


def test_a_malformed_mapping_is_refused(data, enumerate_in):
    mapping = data / "m.yaml"
    mapping.write_text(yaml.safe_dump({"plate_01.csv": ["two", "files"]}))
    with pytest.raises(FanOutFailed):
        enumerate_in(CompiledFanOut(type="mapping_file", mapping=str(mapping)))


# --- folders ---------------------------------------------------------------


def test_folders_yields_one_item_per_subdirectory(tmp_path, enumerate_in):
    root = tmp_path / "experiments"
    for name in ("exp_b", "exp_a"):
        (root / name).mkdir(parents=True)
    (root / "notes.txt").write_text("not a folder")
    items = enumerate_in(CompiledFanOut(type="folders", data_dir=str(root)))
    assert [item["stem"] for item in items] == ["exp_a", "exp_b"]


def test_folders_with_nothing_to_process_is_refused(tmp_path, enumerate_in):
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(FanOutFailed):
        enumerate_in(CompiledFanOut(type="folders", data_dir=str(root)))


# --- patterns --------------------------------------------------------------


def test_patterns_pairs_two_globs_by_position(data, enumerate_in):
    items = enumerate_in(
        CompiledFanOut(
            type="patterns",
            data_dir=str(data),
            raw_pattern="plate_*[0-9].csv",
            meta_pattern="plate_*_meta.csv",
        )
    )
    assert [(item["raw"], item["meta"]) for item in items] == [
        ("plate_01.csv", "plate_01_meta.csv"),
        ("plate_02.csv", "plate_02_meta.csv"),
        ("plate_03.csv", "plate_03_meta.csv"),
    ]


def test_mismatched_pattern_counts_are_refused(data, enumerate_in):
    """Pairing by position across unequal lists would analyse one experiment's
    data against another's metadata — a wrong answer nobody catches by eye."""
    (data / "plate_01_meta.csv").unlink()
    with pytest.raises(FanOutFailed, match="paired by position"):
        enumerate_in(
            CompiledFanOut(
                type="patterns",
                data_dir=str(data),
                raw_pattern="plate_*[0-9].csv",
                meta_pattern="plate_*_meta.csv",
            )
        )


def test_a_pattern_matching_nothing_is_refused(data, enumerate_in):
    with pytest.raises(FanOutFailed):
        enumerate_in(CompiledFanOut(type="patterns", data_dir=str(data), raw_pattern="*.nope"))


# --- containment -----------------------------------------------------------


def test_a_source_outside_every_root_is_refused(data, tmp_path):
    """The path comes from a submitted value, so enumerating it anywhere would
    list directory names from wherever the service account can read."""
    confined = DirectoryFanOut(roots=(tmp_path / "somewhere-else",))
    with pytest.raises(FanOutFailed, match="outside every configured storage root"):
        confined(CompiledFanOut(type="folders", data_dir=str(data)))


def test_traversal_out_of_a_root_is_refused(data):
    confined = DirectoryFanOut(roots=(data,))
    with pytest.raises(FanOutFailed, match="outside every configured storage root"):
        confined(CompiledFanOut(type="folders", data_dir=f"{data}/../.."))


def test_no_configured_roots_refuses_everything(data):
    """The right default for a deployment that has configured none: a rejected
    submission beats one that enumerates the host."""
    with pytest.raises(FanOutFailed):
        DirectoryFanOut()(CompiledFanOut(type="folders", data_dir=str(data)))


def test_an_unresolved_reference_names_the_field_rather_than_the_path(enumerate_in):
    """A value nobody supplied would otherwise surface as a confusing
    'not found' for a path with braces in it."""
    with pytest.raises(FanOutFailed, match="unresolved reference"):
        enumerate_in(CompiledFanOut(type="mapping_file", mapping="{mapping_yaml}"))


def test_a_missing_source_is_refused_clearly(tmp_path, enumerate_in):
    with pytest.raises(FanOutFailed, match="does not exist"):
        enumerate_in(CompiledFanOut(type="folders", data_dir=str(tmp_path / "absent")))
