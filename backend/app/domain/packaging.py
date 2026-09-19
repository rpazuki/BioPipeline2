"""What is installed, and whether that is a fact anyone can reproduce.

No filesystem and no container: this is the arithmetic of a package set, so
the parts that decide whether two environments are the same, and whether
either can be rebuilt, are testable without installing anything.

**The digest is the identity.** Two installs that arrive at the same set of
distributions are the same generation, which is what stops an
install-uninstall-reinstall cycle growing the disk for ever. It is taken over
the *resolved* set — every distribution and version, sorted — not over the
specifier somebody typed, because `pip install pandas` means different things
on different days.

**Editable installs break reproducibility, and saying so is the whole point.**
The real install history has `labUtils` installed from a working tree (G94).
No digest can capture that: it is a link to mutable source, not a version. A
generation containing one is marked, and every run pinning it is marked, so
"what was installed when this ran?" gets an honest answer rather than a
version number that means nothing.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from app.domain.errors import ValidationFailed

# Enough to stop a specifier being shell, a flag, or a second argument. Not a
# full PEP 508 parser: pip is the authority on what it accepts, and the point
# here is that nothing reaches it that could mean something other than a
# package.
SPECIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*(\[[A-Za-z0-9,._-]+\])?([<>=!~][^\s;]*)?$")
SPECIFIER_MAX = 512


class SpecifierRejected(ValidationFailed):
    code = "package.specifier_invalid"


@dataclass(frozen=True, slots=True)
class Package:
    """One installed distribution."""

    name: str
    version: str
    editable_path: str | None = None

    @property
    def is_editable(self) -> bool:
        return self.editable_path is not None

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version, "editable_path": self.editable_path}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Package:
        return cls(
            name=str(raw["name"]),
            version=str(raw.get("version", "")),
            editable_path=raw.get("editable_path") or None,
        )


def check_specifier(specifier: str) -> str:
    """Refuse anything that is not plainly a package requirement.

    An install runs a command inside a container as an administrator asked,
    and the specifier is the one part of it that comes from a request. It is
    passed to pip as a single argument, never through a shell, so this is
    belt and braces -- but `--index-url` or `-e /some/path` slipped into the
    box would be an install nobody reviewed.
    """
    clean = (specifier or "").strip()
    if not clean:
        raise SpecifierRejected("Name a package to install.")
    if len(clean) > SPECIFIER_MAX:
        raise SpecifierRejected(f"A package specifier cannot be longer than {SPECIFIER_MAX}.")
    if not SPECIFIER.match(clean):
        raise SpecifierRejected(
            f"'{clean}' is not a package name and version. Flags, paths and URLs are "
            "not accepted here; an editable or local install is done on the host by "
            "somebody who can see what they are installing."
        )
    return clean


def read_inventory(raw: Any) -> list[Package]:
    """Read `pip list --format=json`, including its editable marker.

    pip reports an editable install as `editable_project_location`. Older pip
    used `location` with a `-e` flag in the plain format; the JSON output is
    read instead precisely so this does not have to be parsed out of text.
    """
    if isinstance(raw, str):
        raw = json.loads(raw or "[]")
    if not isinstance(raw, list):
        raise ValidationFailed("The package inventory was not a list.")
    packages = [
        Package(
            name=str(entry.get("name", "")),
            version=str(entry.get("version", "")),
            editable_path=entry.get("editable_project_location") or None,
        )
        for entry in raw
        if isinstance(entry, dict) and entry.get("name")
    ]
    return sorted(packages, key=lambda package: package.name.lower())


def digest_of(packages: list[Package]) -> str:
    """A content identity for a package set.

    Editable installs are included by *path*, which is honest rather than
    useful: it makes two generations differ when one points at a working tree
    and the other does not, while making no claim that the path's contents
    are the same twice.
    """
    material = "\n".join(
        f"{package.name.lower()}=={package.version}"
        + (f"@editable:{package.editable_path}" if package.is_editable else "")
        for package in packages
    )
    return "sha256:" + hashlib.sha256(material.encode()).hexdigest()


def is_reproducible(packages: list[Package]) -> bool:
    """Whether this set could be rebuilt from its own record."""
    return not any(package.is_editable for package in packages)


def describe_editables(packages: list[Package]) -> str | None:
    """What to tell somebody whose run is not reproducible."""
    editable = [package for package in packages if package.is_editable]
    if not editable:
        return None
    names = ", ".join(f"{package.name} ({package.editable_path})" for package in editable)
    return (
        f"Installed from a working tree: {names}. A run using this environment "
        "records what it used, but the source can change underneath it, so the "
        "run cannot be reproduced from this record alone."
    )
