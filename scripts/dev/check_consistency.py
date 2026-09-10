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
    "15-premise-correction.md", "gaps.md", "gap2.md",
    "14-gap-closure-ledger.md", "01-critical-review.md", "13-open-questions.md",
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


def failures() -> list[str]:
    problems: list[str] = []

    # 1. Superseded vocabulary in active documents and in code.
    targets = [
        p for p in (ROOT / "migration").glob("*.md") if p.name not in HISTORICAL
    ]
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
    accepted = [p for p in adrs if "Status: Accepted" in p.read_text()]
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

    # 4. Every ADR referenced from a document must exist.
    known = {p.name.split("-")[0] for p in adrs}
    for path in (ROOT / "migration").glob("*.md"):
        for number in re.findall(r"ADR (\d{4})", path.read_text()):
            if number not in known:
                problems.append(f"{path.name}: references ADR {number}, which does not exist")

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
