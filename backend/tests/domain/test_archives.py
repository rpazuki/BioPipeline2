"""Reject archive paths and contents that cannot be staged safely."""

import stat
import struct
import zipfile

import pytest

from app.domain.errors import LimitExceeded, ValidationFailed
from app.infrastructure.archives import extract_zip, member_path


@pytest.mark.parametrize(
    "name", ["../x", "/x", "C:/x", "a\\b", "a/../b", "a//b", "./x", "a/./x", "a\x00x", "a:x", ""]
)
def test_unsafe_member_names_are_rejected(name):
    with pytest.raises(ValidationFailed):
        member_path(name)


def archive(tmp_path, entries):
    source = tmp_path / "input.zip"
    with zipfile.ZipFile(source, "w") as output:
        for name, body in entries:
            output.writestr(name, body)
    target = tmp_path / "expanded"
    target.mkdir()
    return source, target


def test_nested_and_empty_members_are_preserved(tmp_path):
    source, target = archive(
        tmp_path, [("empty/", b""), ("nested/a.txt", b"content"), ("zero.txt", b"")]
    )
    extract_zip(source, target, max_bytes=100, max_files=10)
    assert (target / "empty").is_dir()
    assert (target / "nested/a.txt").read_bytes() == b"content"
    assert (target / "zero.txt").read_bytes() == b""


@pytest.mark.parametrize(
    "entries",
    [
        [("same", b"a"), ("same", b"b")],
        [("A", b"a"), ("a", b"b")],
        [("a", b"file"), ("a/child", b"child")],
        [("../escape", b"bad")],
    ],
)
def test_duplicate_and_conflicting_destinations_are_rejected(tmp_path, entries):
    source, target = archive(tmp_path, entries)
    with pytest.raises(ValidationFailed):
        extract_zip(source, target, max_bytes=100, max_files=10)
    assert not list(target.iterdir())


def test_symbolic_links_are_rejected(tmp_path):
    member = zipfile.ZipInfo("link")
    member.create_system = 3
    member.external_attr = (stat.S_IFLNK | 0o777) << 16
    source, target = archive(tmp_path, [(member, b"/etc/passwd")])
    with pytest.raises(ValidationFailed):
        extract_zip(source, target, max_bytes=100, max_files=10)


@pytest.mark.parametrize("max_bytes,max_files", [(1, 10), (100, 1)])
def test_expansion_limits_are_enforced(tmp_path, max_bytes, max_files):
    source, target = archive(tmp_path, [("a", b"1234"), ("b", b"5678")])
    with pytest.raises(LimitExceeded):
        extract_zip(source, target, max_bytes=max_bytes, max_files=max_files)


def test_corrupt_zip_is_reported_as_validation_failure(tmp_path):
    source = tmp_path / "bad.zip"
    source.write_bytes(b"not a ZIP")
    with pytest.raises(ValidationFailed):
        extract_zip(source, tmp_path, max_bytes=100, max_files=10)


def test_the_zip_member_count_claim_cannot_bypass_limits(tmp_path):
    source, target = archive(tmp_path, [("a", b"a"), ("b", b"b")])
    raw = bytearray(source.read_bytes())
    end = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<HH", raw, end + 8, 1, 1)
    source.write_bytes(raw)
    with pytest.raises(LimitExceeded):
        extract_zip(source, target, max_bytes=100, max_files=1)


def test_large_directory_metadata_is_rejected_before_loading_it(tmp_path):
    source, target = archive(tmp_path, [("a", b"a")])
    raw = bytearray(source.read_bytes())
    end = raw.rfind(b"PK\x05\x06")
    struct.pack_into("<I", raw, end + 12, 17 * 1024 * 1024)
    source.write_bytes(raw)
    with pytest.raises(LimitExceeded):
        extract_zip(source, target, max_bytes=100, max_files=10)
