#!/usr/bin/env python3
"""Guard the plan and the code against silently disagreeing.

A second review found the planning documents, the ADRs, the code and the
READMEs describing four different systems: a superseded `${{ }}` syntax still
implemented and advertised, a separate Workflow resource in the API and
frontend docs, "all 25 ADRs are Proposed" when sixteen were accepted, and a
table count that was wrong by three.

None of those were caught by tests, because tests of a superseded contract
pass perfectly well. This script checks the claims instead.

Run it from `make check`.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
ADR_DIR = ROOT / "migration/docs/adr"

# Documents that are the historical record and must keep superseded wording.
HISTORICAL = {
    "15-premise-correction.md",
    "gaps.md",
    "gap2.md",
    "14-gap-closure-ledger.md",
    "01-critical-review.md",
    "13-open-questions.md",
}

# A line that explicitly says the term is gone is not a violation: documents
# have to be able to explain what was removed and why.
SUPERSEDING = re.compile(
    r"removed|superseded|replaced|replaces|dropped|deleted|no longer|invented|"
    r"void|was wrong|instead of|rather than|~~",
    re.IGNORECASE,
)

# Superseded vocabulary that must not appear in active material.
FORBIDDEN = {
    r"\$\{\{": "the `${{ }}` syntax was replaced by `{brace}` references (ADR 0027)",
    r"\bWorkflowRevision\b": "one authoring level: PipelineRevision (ADR 0026)",
    r"\bWorkflowTemplate\b": "one authoring level: Pipeline (ADR 0026)",
    r"\bworkflow_revisions\b": "table renamed to pipeline_revisions (ADR 0026)",
    r"\bworkflow_templates\b": "table renamed to pipelines (ADR 0026)",
    r"\btype_definition_heads\b": "type versioning was removed; types freeze by snapshot",
    r"\blegacy_import_map\b": "no migration is happening (ADR 0018)",
    r"\boutbox_events\b": "dropped; no consumer at this scale",
}


UNWRITTEN = re.compile(r"^(\s*)([\w./-]+/)\s+.*\(not written yet\)")


def unwritten_but_written() -> list[str]:
    """Directories the README calls unwritten that now have code in them.

    The layout block is an indented tree, so a line's path is its own name
    under whichever shallower line came before it.
    """
    problems: list[str] = []
    stack: list[tuple[int, str]] = []
    for line_no, line in enumerate((ROOT / "README.md").read_text().splitlines(), start=1):
        match = re.match(r"^(\s*)([\w./-]+/)", line)
        if not match:
            continue
        indent, name = len(match.group(1)), match.group(2)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = (stack[-1][1] if stack else "") + name
        stack.append((indent, path))
        if not UNWRITTEN.match(line):
            continue
        directory = ROOT / path
        written = [p for p in directory.rglob("*.py") if "__pycache__" not in p.parts]
        if written:
            problems.append(
                f"README.md:{line_no}: '{path}' is called unwritten and holds "
                f"{len(written)} Python file(s)"
            )
    return problems


def failures() -> list[str]:
    problems: list[str] = []

    # 1. Superseded vocabulary in active documents and in code.
    targets = [p for p in (ROOT / "migration").glob("*.md") if p.name not in HISTORICAL]
    targets += list((ROOT / "backend/app").rglob("*.py"))
    targets += [ROOT / "README.md", ROOT / "ASSUMPTIONS.md"]
    for path in targets:
        if not path.is_file():
            continue
        text = path.read_text(errors="replace")
        for pattern, reason in FORBIDDEN.items():
            for match in re.finditer(pattern, text):
                line_no = text[: match.start()].count("\n") + 1
                line = text.splitlines()[line_no - 1]
                if SUPERSEDING.search(line):
                    continue
                rel = path.relative_to(ROOT)
                problems.append(f"{rel}:{line_no}: '{match.group(0)}' — {reason}")

    # 2. Claimed ADR counts must match reality.
    adrs = sorted(ADR_DIR.glob("0*.md"))
    # The header line, not the substring: a record that *explains* how to
    # accept it contains the words "Status: Accepted" without being accepted.
    accepted = [p for p in adrs if _status_of(p) == "Accepted"]
    for name in ("README.md", "ASSUMPTIONS.md"):
        text = (ROOT / name).read_text()
        for claimed, total in re.findall(r"(\d+) of (\d+) ADRs", text):
            if (int(claimed), int(total)) != (len(accepted), len(adrs)):
                problems.append(
                    f"{name}: claims {claimed} of {total} ADRs accepted; "
                    f"actual is {len(accepted)} of {len(adrs)}"
                )

    # 3. Claimed table counts must match the models.
    sys.path.insert(0, str(ROOT / "backend"))
    from app.infrastructure.db.models import Base  # noqa: PLC0415

    actual = len(Base.metadata.tables)
    for name in ("README.md",):
        for claimed in re.findall(r"(\d+) tables", (ROOT / name).read_text()):
            if int(claimed) != actual:
                problems.append(
                    f"{name}: claims {claimed} tables; models define {actual}"
                )

    # 4. "Not written yet" must still be true.
    #
    # The repository-layout block called `application/`, `api/` and `workers/`
    # unwritten for three commits after they were written, because nothing
    # compares a README's tree against the tree. This does.
    problems += unwritten_but_written()

    # 5b. The ADR index must agree with the ADR files, and every document must
    # agree with both.
    #
    # Evaluation 1 found records marked accepted that nobody had approved, and
    # a consistency check that passed anyway. A status is a claim about
    # governance, so it is worth the same enforcement as a table count.
    problems += adr_index_disagreements(adrs)

    # 5. Every ADR referenced from a document must exist.
    known = {p.name.split("-")[0] for p in adrs}
    for path in (ROOT / "migration").glob("*.md"):
        for number in re.findall(r"ADR (\d{4})", path.read_text()):
            if number not in known:
                problems.append(
                    f"{path.name}: references ADR {number}, which does not exist"
                )

    return problems


STATUS_BY_SECTION = {
    "Decided": {"Accepted", "Superseded"},
    "Implemented, pending ratification": {"Implemented proposal - pending ratification"},
    "Still open": {"Proposed"},
}


def _status_of(path: pathlib.Path) -> str:
    """The status, normalised.

    `Accepted (moot)` and `Accepted (amended 2026-09-10)` are both accepted;
    the parenthetical is commentary. Anything else is reported as written,
    because an unrecognised status is usually a typo that makes a record
    invisible to every check below.
    """
    match = re.search(r"^Status: (.+)$", path.read_text(), flags=re.M)
    raw = match.group(1).strip() if match else "(none)"
    for known in ("Accepted", "Implemented proposal", "Superseded", "Proposed"):
        if raw.startswith(known):
            return "Implemented proposal - pending ratification" if known.startswith(
                "Implemented"
            ) else known
    return raw


def adr_index_disagreements(adrs: list[pathlib.Path]) -> list[str]:
    """Each ADR's own status, against the section of the index listing it.

    The index is what everything else reads. A record that says `Proposed`
    while the index calls it decided is how an open question disappears behind
    an optimistic summary.
    """
    problems: list[str] = []
    statuses = {path.name.split("-")[0]: _status_of(path) for path in adrs}
    text = (ADR_DIR / "README.md").read_text()

    section = ""
    counted = {name: 0 for name in STATUS_BY_SECTION}
    for line in text.splitlines():
        heading = re.match(r"^## (.+)$", line)
        if heading:
            section = heading.group(1).strip()
            continue
        listed = re.match(r"^\| \[(\d{4})\]", line)
        if not listed or section not in STATUS_BY_SECTION:
            continue
        number = listed.group(1)
        counted[section] += 1
        allowed = STATUS_BY_SECTION[section]
        actual = statuses.get(number, "(missing file)")
        if actual not in allowed:
            problems.append(
                f"docs/adr/README.md: ADR {number} is listed under '{section}' "
                f"but its status is '{actual}'"
            )

    for number, status in statuses.items():
        if status not in {s for group in STATUS_BY_SECTION.values() for s in group}:
            problems.append(f"ADR {number}: unknown status '{status}'")

    # Whitespace-insensitive: the sentence is wrapped in the source.
    claim = re.search(
        r"\*\*(\d+) of (\d+) are decided, (\d+) are implemented and awaiting "
        r"ratification, and (\d+) are open\.\*\*",
        " ".join(text.split()),
    )
    if claim is None:
        problems.append("docs/adr/README.md: the counted summary sentence is missing")
    else:
        decided, total, pending, open_ = (int(value) for value in claim.groups())
        real = (
            counted["Decided"],
            len(adrs),
            counted["Implemented, pending ratification"],
            counted["Still open"],
        )
        if (decided, total, pending, open_) != real:
            problems.append(
                f"docs/adr/README.md: claims {decided} decided / {pending} pending / "
                f"{open_} open of {total}; the index lists {real[0]} / {real[2]} / "
                f"{real[3]} of {real[1]}"
            )
    return problems


def main() -> int:
    problems = failures()
    if not problems:
        print("consistency: plan, ADRs, code and READMEs agree")
        return 0
    print(f"consistency: {len(problems)} problem(s)\n", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
