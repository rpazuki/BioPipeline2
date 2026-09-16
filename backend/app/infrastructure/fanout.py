"""Resolving a fan-out source to its items.

The one piece of materialisation that has to touch a filesystem, which is why
the domain takes it as an injected callable and never imports this module.
Without an implementation a stage that fans out cannot be submitted at all —
and fan-out is not an edge case here: one task per plate-reader export, per
experiment folder, per matched raw/metadata pair *is* the shape of this work.

**Containment is the whole risk.** The source path comes from a submitted
value: `fanout.mapping: "{mapping_yaml}"` is whatever a researcher supplied.
Enumerating an arbitrary path would list directory names from anywhere the
service account can read, and put them in a run record. So every path is
resolved and then checked against an allowlist of roots, exactly as component
libraries and workspaces are.

Items expose `raw`, `meta` and `stem`. `stem` is what names the task and its
output directory, so it has to be stable and filesystem-safe.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.domain.errors import ValidationFailed
from app.domain.ir import CompiledFanOut


class FanOutFailed(ValidationFailed):
    """The source could not be enumerated, so the run cannot be built."""

    code = "fanout.unresolvable"


@dataclass(frozen=True, slots=True)
class DirectoryFanOut:
    """Enumerates fan-out sources, confined to a set of roots.

    ``roots`` are the directories a submission may name — in practice the
    attested shared-storage roots plus the run's own upload area. An empty set
    refuses everything, which is the right default for a deployment that has
    not configured any: better a submission that is rejected than one that
    enumerates the host.
    """

    roots: tuple[Path, ...] = ()

    def __call__(self, fanout: CompiledFanOut) -> list[dict[str, Any]]:
        if fanout.type == "mapping_file":
            return self._from_mapping(self._contained(fanout.mapping, "mapping"))
        if fanout.type == "folders":
            return self._from_folders(self._contained(fanout.data_dir, "data_dir"))
        if fanout.type == "patterns":
            return self._from_patterns(
                self._contained(fanout.data_dir, "data_dir"),
                fanout.raw_pattern or "*",
                fanout.meta_pattern,
            )
        raise FanOutFailed(
            f"Cannot enumerate a fan-out of type '{fanout.type}'.",
            details={"type": fanout.type},
        )

    # --- containment ------------------------------------------------------

    def _contained(self, raw: str | None, field: str) -> Path:
        if not raw:
            raise FanOutFailed(f"The fan-out is missing '{field}'.", details={"field": field})
        if "{" in raw:
            # An unrendered reference means a value nobody supplied. Enumerating
            # a path with braces in it would produce a confusing "not found"
            # instead of naming the input that is missing.
            raise FanOutFailed(
                f"'{field}' still contains an unresolved reference: {raw}",
                details={"field": field, "value": raw},
            )
        candidate = Path(raw).resolve()
        if not any(
            candidate == root or candidate.is_relative_to(root) for root in self._resolved_roots()
        ):
            # Deliberately does not echo the resolved path: whether a path
            # outside the allowlist exists is not something a submission should
            # be able to probe.
            raise FanOutFailed(
                f"'{field}' is outside every configured storage root.",
                details={"field": field},
            )
        if not candidate.exists():
            raise FanOutFailed(f"'{field}' does not exist: {raw}", details={"field": field})
        return candidate

    def _resolved_roots(self) -> tuple[Path, ...]:
        return tuple(root.resolve() for root in self.roots)

    # --- kinds ------------------------------------------------------------

    def _from_mapping(self, path: Path) -> list[dict[str, Any]]:
        """A YAML of `raw: meta` filenames, relative to the mapping's folder.

        Relative to the mapping rather than to a data root, because that is
        where the pairing is written down and it keeps the mapping movable.
        """
        try:
            document = yaml.safe_load(path.read_text())
        except (OSError, yaml.YAMLError) as error:
            raise FanOutFailed(f"The mapping file could not be read: {error}") from error
        if not isinstance(document, dict) or not document:
            raise FanOutFailed(
                "A mapping file must be a non-empty mapping of raw file to metadata file."
            )

        items: list[dict[str, Any]] = []
        for raw, meta in document.items():
            if not isinstance(raw, str) or not isinstance(meta, str):
                raise FanOutFailed(
                    "Every mapping entry must be 'raw filename: metadata filename'.",
                    details={"entry": str(raw)},
                )
            items.append({"raw": raw, "meta": meta, "stem": Path(raw).stem})
        return items

    def _from_folders(self, path: Path) -> list[dict[str, Any]]:
        """One item per immediate subdirectory."""
        folders = sorted(child for child in path.iterdir() if child.is_dir())
        if not folders:
            raise FanOutFailed(f"No folders to process in {path.name}.")
        return [{"raw": child.name, "meta": None, "stem": child.name} for child in folders]

    def _from_patterns(
        self, path: Path, raw_pattern: str, meta_pattern: str | None
    ) -> list[dict[str, Any]]:
        """Two globs paired by position.

        Sorted, and refused when the counts differ: pairing by position across
        lists of different lengths would silently analyse one experiment's data
        against another's metadata, which is the kind of wrong answer nobody
        catches by looking at it.
        """
        raws = sorted(child.name for child in path.glob(raw_pattern) if child.is_file())
        if not raws:
            raise FanOutFailed(f"No files matched '{raw_pattern}' in {path.name}.")
        if meta_pattern is None:
            return [{"raw": name, "meta": None, "stem": Path(name).stem} for name in raws]

        metas = sorted(child.name for child in path.glob(meta_pattern) if child.is_file())
        if len(metas) != len(raws):
            raise FanOutFailed(
                f"'{raw_pattern}' matched {len(raws)} files but '{meta_pattern}' "
                f"matched {len(metas)}; they are paired by position and must agree.",
                details={"raw_matches": len(raws), "meta_matches": len(metas)},
            )
        return [
            {"raw": raw, "meta": meta, "stem": Path(raw).stem}
            for raw, meta in zip(raws, metas, strict=True)
        ]
