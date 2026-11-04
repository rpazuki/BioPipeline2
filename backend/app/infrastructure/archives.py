"""Validate and extract bounded ZIP archives into private temporary directories."""

from __future__ import annotations

import stat
import struct
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from app.domain.errors import LimitExceeded, ValidationFailed

BUFFER = 1024 * 1024
MAX_DIRECTORY_BYTES = 16 * 1024 * 1024


def _check_directory(source: Path, max_files: int) -> None:
    """Bound ZIP metadata and count actual headers before allocating member objects."""
    with source.open("rb") as reader:
        # Reuse Python's end-record reader for ordinary and ZIP64 offsets.
        end = zipfile._EndRecData(reader)
        if end is None:
            raise zipfile.BadZipFile("Missing ZIP end record")
        size = end[zipfile._ECD_SIZE]
        if size > MAX_DIRECTORY_BYTES:
            raise LimitExceeded("The ZIP directory metadata exceeds 16 mebibytes.")
        start = end[zipfile._ECD_LOCATION] - size
        if end[zipfile._ECD_SIGNATURE] == zipfile.stringEndArchive64:
            start -= zipfile.sizeEndCentDir64 + zipfile.sizeEndCentDir64Locator
        if start < 0:
            raise zipfile.BadZipFile("Invalid ZIP directory offset")
        reader.seek(start)
        consumed = 0
        count = 0
        while consumed < size:
            header = reader.read(zipfile.sizeCentralDir)
            if len(header) != zipfile.sizeCentralDir:
                raise zipfile.BadZipFile("Truncated ZIP directory")
            fields = struct.unpack(zipfile.structCentralDir, header)
            if fields[zipfile._CD_SIGNATURE] != zipfile.stringCentralDir:
                raise zipfile.BadZipFile("Invalid ZIP directory header")
            count += 1
            if count > max_files:
                raise LimitExceeded(f"The ZIP contains more than {max_files} members.")
            extra = sum(
                fields[index]
                for index in (
                    zipfile._CD_FILENAME_LENGTH,
                    zipfile._CD_EXTRA_FIELD_LENGTH,
                    zipfile._CD_COMMENT_LENGTH,
                )
            )
            consumed += zipfile.sizeCentralDir + extra
            if consumed > size:
                raise zipfile.BadZipFile("Invalid ZIP directory length")
            reader.seek(extra, 1)


def member_path(value: str) -> str:
    """Accept a portable relative member name without traversal or alternate separators."""
    path = PurePosixPath(value)
    if (
        not value
        or len(value.encode("utf-8")) > 1024
        or path.is_absolute()
        or path.as_posix() != value
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(len(part.encode("utf-8")) > 255 for part in value.split("/"))
        or any(ord(character) < 32 for character in value)
    ):
        raise ValidationFailed(f"Unsafe directory member path: {value!r}.")
    return unicodedata.normalize("NFC", value)


def check_members(entries: list[tuple[str, bool]], *, max_members: int | None = None) -> list[str]:
    """Reject duplicate destinations and files used as parent directories."""
    known: dict[str, bool] = {}
    names = []
    for raw, directory in entries:
        name = member_path(raw)
        canonical = name.casefold()
        if canonical in known:
            raise ValidationFailed(f"Duplicate directory destination: {name}.")
        known[canonical] = directory
        names.append(name)
    all_members = set(known)
    for name in known:
        for parent in PurePosixPath(name).parents:
            if str(parent) != "." and known.get(str(parent)) is False:
                raise ValidationFailed("A file cannot also be a parent directory.")
            if str(parent) != ".":
                all_members.add(str(parent))
            if max_members is not None and len(all_members) > max_members:
                raise LimitExceeded(f"The directory exceeds {max_members} members.")
    return names


def extract_zip(source: Path, destination: Path, *, max_bytes: int, max_files: int) -> None:
    """Extract regular files and directories while checking declared and actual limits.

    Rejects links, special files, encrypted members, unsafe paths and duplicate
    destinations. Raises ValidationFailed or LimitExceeded before retaining output.
    """
    try:
        _check_directory(source, max_files)
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > max_files:
                raise LimitExceeded(f"The ZIP contains more than {max_files} members.")
            names = check_members(
                [
                    (entry.filename[:-1] if entry.is_dir() else entry.filename, entry.is_dir())
                    for entry in entries
                ],
                max_members=max_files,
            )
            if sum(entry.file_size for entry in entries) > max_bytes:
                raise LimitExceeded(f"The ZIP expands beyond {max_bytes} bytes.")
            for entry in entries:
                if entry.orig_filename != entry.filename:
                    raise ValidationFailed("ZIP member names cannot contain NUL characters.")
                mode = stat.S_IFMT(entry.external_attr >> 16)
                allowed = {0, stat.S_IFDIR} if entry.is_dir() else {0, stat.S_IFREG}
                if mode not in allowed or entry.flag_bits & 1:
                    raise ValidationFailed(
                        "ZIP links, special files and encrypted members are unsupported."
                    )
                if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                    raise ValidationFailed("Use an uncompressed or deflated ZIP archive.")
            total = 0
            for entry, name in zip(entries, names, strict=True):
                target = destination / name
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as reader, target.open("xb") as writer:
                    while block := reader.read(BUFFER):
                        total += len(block)
                        if total > max_bytes:
                            raise LimitExceeded(f"The ZIP expands beyond {max_bytes} bytes.")
                        writer.write(block)
    except (
        zipfile.BadZipFile,
        RuntimeError,
        EOFError,
        NotImplementedError,
        UnicodeError,
        ValueError,
        struct.error,
    ) as error:
        raise ValidationFailed("The ZIP is corrupt, encrypted, or unsupported.") from error
