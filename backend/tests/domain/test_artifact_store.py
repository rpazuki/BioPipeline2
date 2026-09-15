"""The artifact store: promotion, containment, manifests, deletion."""

from __future__ import annotations

import uuid

import pytest

from app.infrastructure.artifacts import ArtifactStoreError, PosixArtifactStore


@pytest.fixture
def store(tmp_path):
    return PosixArtifactStore(tmp_path / "artifacts")


@pytest.fixture
def source(tmp_path):
    directory = tmp_path / "ws" / "outputs"
    directory.mkdir(parents=True)
    return directory


def _key(store, output_key="results", attempt=1) -> str:
    return store.key_for(
        run_id=uuid.uuid4(), task_key="fit:a", attempt=attempt, output_key=output_key
    )


# --- keys -----------------------------------------------------------------


def test_a_key_is_built_from_identifiers_the_platform_controls(store):
    """Never from a filename a task chose."""
    key = store.key_for(run_id=uuid.UUID(int=1), task_key="fit:a#step", attempt=2, output_key="r")
    assert key.startswith("runs/00000000-0000-0000-0000-000000000001/")
    assert ":" not in key and "#" not in key


def test_each_attempt_gets_its_own_key(store):
    """Live artifacts are unique on their storage key, so a retry must not
    collide with the attempt it is replacing."""
    run_id = uuid.uuid4()
    first = store.key_for(run_id=run_id, task_key="t", attempt=1, output_key="r")
    second = store.key_for(run_id=run_id, task_key="t", attempt=2, output_key="r")
    assert first != second


@pytest.mark.parametrize("key", ["../escape", "/etc/passwd", "runs/../../out"])
def test_a_key_that_escapes_the_root_is_refused(store, key):
    with pytest.raises(ArtifactStoreError, match="outside the artifact root"):
        store.path_for(key)


# --- promoting files ------------------------------------------------------


def test_a_file_is_promoted_with_its_checksum(store, source):
    (source / "r.txt").write_text("data")
    stored = store.put(source / "r.txt", _key(store))
    assert stored.size_bytes == 4
    assert stored.checksum_sha256 is not None
    assert not stored.is_directory
    assert store.exists(stored.storage_key)


def test_promotion_hardlinks_rather_than_copying_when_it_can(store, source):
    """Copying doubles the disk cost of every run. With RNA-seq outputs in
    tens of gigabytes that is the difference between a VM that works and one
    that fills up."""
    (source / "big.bin").write_bytes(b"x" * 4096)
    stored = store.put(source / "big.bin", _key(store))
    assert stored.linked, "expected a hardlink on a single filesystem"
    assert (source / "big.bin").stat().st_ino == store.path_for(stored.storage_key).stat().st_ino


def test_promoting_something_that_does_not_exist_is_refused(store, source):
    with pytest.raises(ArtifactStoreError, match="does not exist"):
        store.put(source / "absent", _key(store))


def test_promotion_is_idempotent_for_the_same_key(store, source):
    (source / "r.txt").write_text("data")
    key = _key(store)
    store.put(source / "r.txt", key)
    again = store.put(source / "r.txt", key)
    assert again.size_bytes == 4


# --- promoting directories ------------------------------------------------


def test_a_directory_is_promoted_as_a_directory(store, source):
    """Packaging a large output tree into one archive is neither fast nor
    useful, so the tree is kept and described by a manifest."""
    tree = source / "many"
    (tree / "nested").mkdir(parents=True)
    (tree / "a.txt").write_text("aa")
    (tree / "nested" / "b.txt").write_text("bbb")
    stored = store.put(tree, _key(store))
    assert stored.is_directory
    assert stored.size_bytes == 5
    assert store.path_for(stored.storage_key).is_dir()


def test_a_manifest_lists_every_file_with_a_checksum(store, source):
    tree = source / "many"
    tree.mkdir()
    (tree / "a.txt").write_text("aa")
    (tree / "b.txt").write_text("bbb")
    stored = store.put(tree, _key(store))
    entries = store.manifest(stored.storage_key)
    assert {entry.relative_path for entry in entries} == {"a.txt", "b.txt"}
    assert all(len(entry.checksum_sha256) == 64 for entry in entries)


def test_a_symlink_inside_a_directory_is_not_followed(store, source, tmp_path):
    """A link could point outside the workspace, and promoting what it points
    at would copy bytes the task was never supposed to reach."""
    secret = tmp_path / "secret.txt"
    secret.write_text("classified")
    tree = source / "many"
    tree.mkdir()
    (tree / "ok.txt").write_text("fine")
    (tree / "link").symlink_to(secret)
    stored = store.put(tree, _key(store))
    promoted = store.path_for(stored.storage_key)
    assert (promoted / "ok.txt").is_file()
    assert not (promoted / "link").exists()


def test_a_manifest_of_a_file_artifact_is_empty(store, source):
    (source / "r.txt").write_text("data")
    stored = store.put(source / "r.txt", _key(store))
    assert store.manifest(stored.storage_key) == []


# --- deletion -------------------------------------------------------------


def test_deleting_reports_whether_anything_was_there(store, source):
    """The janitor needs to tell "purged now" from "already gone" without
    treating the second as an error."""
    (source / "r.txt").write_text("data")
    stored = store.put(source / "r.txt", _key(store))
    assert store.delete(stored.storage_key) is True
    assert store.delete(stored.storage_key) is False
    assert not store.exists(stored.storage_key)


def test_deleting_a_directory_removes_the_tree(store, source):
    tree = source / "many"
    tree.mkdir()
    (tree / "a.txt").write_text("aa")
    stored = store.put(tree, _key(store))
    assert store.delete(stored.storage_key) is True
    assert not store.exists(stored.storage_key)


def test_deleting_an_escaping_key_does_nothing(store):
    assert store.delete("../../etc/passwd") is False
