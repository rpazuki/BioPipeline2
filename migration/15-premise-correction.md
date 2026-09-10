# Premise Correction

Date: 2026-09-10
Supersedes: parts of 01-14, listed below

Documents 01-14 were written from a reading of the existing repository and its
name. That reading was wrong about what the project is, and the error
propagated into the architecture, the data model, the non-functional
requirements, and the roadmap.

This document records the correction, the evidence for it, and which parts of
the plan it invalidates. It is deliberately blunt: a design folder that quietly
patches its own mistakes is how the documentation drift diagnosed in document
01 begins.

## What the plan assumed

> "a bioinformatics platform likely holding human-derived data"
> — [11-non-functional-requirements.md](11-non-functional-requirements.md)

From the name `bioPipeline` and the presence of `labUtils`, the plan inferred a
**domain-specific bioinformatics data platform**: one that holds a corpus of
scientific data, needs a data-classification tier, encryption at rest, DPIA
sign-off, residency rules, and TB-scale genomics file handling.

## What the project actually is

**A generic Python execution and orchestration platform.**

- A **pipeline** is a declarative graph of Python function calls — `package` +
  `method` + `parameters`, wired by name.
- The functions are ordinary Python. Nothing in the platform is
  biology-specific; `labUtils` is simply what the current pipelines import. It
  can execute any installed library, related to biology or not.
- **The platform holds no data.** The user supplies inputs at run time; outputs
  are returned; nothing is retained as a corpus. Run history survives, bytes do
  not.
- The value is turning pipelines into parameterised jobs that non-authors can
  run from a form.

The name is a name, not a domain constraint.

## What this invalidated

| Document | What was wrong |
| --- | --- |
| [11](11-non-functional-requirements.md) | The entire data-governance section. Classification tiers, encryption-at-rest mandate, DPIA gate, residency, and "verifiable deletion through backups" are controls for a system that holds a corpus. Replaced by transient-handling and prompt-cleanup requirements. |
| [11](11-non-functional-requirements.md) | The load framing. Real measured task duration is 0.8 s to 47.8 s; the plan speculated about TB-scale genomics. The speculation turned out to matter for *planned* RNA-seq work, but not for the reasons given, and not with the data-governance consequences attached. |
| [06](06-execution-and-operations.md) | Replacing UI package installs with immutable pinned images. Admins install libraries into a shared environment as normal work; a frozen image turns every install into an image build. Replaced by a mutable environment plus per-run snapshots. |
| [10](10-feature-parity-and-scope.md) | Row 12 called the image replacement "the right call". It was not. |
| [03](03-domain-model.md) | The `${{ }}` expression language. Invented; the project already has `{brace}` templating with a whole-value convention. |
| [03](03-domain-model.md) | The two-level Pipeline/Workflow split. Collapsed into one `Pipeline`. |
| [03](03-domain-model.md), [04](04-data-model-postgres.md) | Type versioning with a current-version pointer and version-pinned saved values. The real system has no type versioning at all; it snapshots the type schema into publications and saved values. Snapshot-on-publish replaces both. |
| [04](04-data-model-postgres.md) | `legacy_import_map`, and the requirement that every importer be re-runnable. There is no migration. |
| [09](09-migration-roadmap.md) | Phases 8, 9 and 10 — importers, parallel running, cutover. Nothing is being migrated. |
| [06](06-execution-and-operations.md) | Rootless Podman, SELinux volume labels, Red Hat specifics. Docker on a generic Linux VM. |
| [06](06-execution-and-operations.md), [11](11-non-functional-requirements.md) | Fair-share scheduling, per-user quotas, SSO, multi-project scoping. One lab of 5–20 people does not need them. |
| [04](04-data-model-postgres.md) | `outbox_events`. No consumer worth building at this scale. |
| [01](01-critical-review.md) | Its condemnation of published-field YAML-path bindings. See below. |

## What the plan got right, and one thing it got backwards

Right, and confirmed by the real data: the run/task/attempt split, immutable
revisions, leases over claim flags, schedule-fire idempotency, path containment,
TTL retention with surviving history, and the diagnosis that the word "job" was
overloaded past usefulness.

**Backwards:** document 01 condemned "published field bindings that patch
arbitrary YAML paths", and my review endorsed removing them. Looking at a real
published job, the binding model is earning its keep:

```json
{"target": "definition_path",   "path": ["defaults", "od600_col"]}
{"target": "stage_process_arg", "stage": "growth_rate_fit_pipeline",
                                "process": "df_fit_max_growth_rate",
                                "parameter": "moving_window_size"}
```

It lets an admin expose *any* value in a definition as a form control without
pre-declaring it. The plan's replacement — declare every public input at the
boundary — is strictly more work and less flexible.

The defensible half of the criticism is *when* the binding is resolved, not that
it exists. Resolving it at publish time into the compiled IR keeps the flexible
authoring experience while making a binding to a nonexistent process fail at
publish rather than vanish silently at run time.

## The finding that justifies the compiler rules

Analysis of 2,178 real task specifications found **509 (23%) containing an
unresolved `{...}` reference passed through as a raw mapping**:

```json
"df_combined_fit_2": {"on_cols": [{"variant.group_cols_2": null}]}
```

The scientific results are unaffected — the reference appears only in pipelines
that do not define that process, so the value never reached a function. But it
was harmless by accident, through two independent silent failures cancelling
out:

1. An unresolved template reference is passed through instead of raising.
2. A `process_arg_mapping` override naming a process absent from the target
   pipeline is silently dropped.

Either one, alone, turns a typo into a successful run that quietly did not
apply a setting. This is the evidence behind the two compiler rules in
[03](03-domain-model.md): an unresolvable reference is a compile error, and a
binding to a nonexistent target fails at publish.

A related finding: typed values are submitted as strings and never coerced —
`{"n_samples": "200", "seed": "42", "max_time": "24.0"}` against a type library
declaring integer, integer, float.

## A methodological note

Two errors in the review process itself are worth recording, because both are
repeatable:

**Reasoning from the name.** "Bioinformatics" carried a set of assumptions —
genomic data, regulatory exposure, TB-scale files — that were never checked
against the code. The correct move was to ask what the platform does before
designing for what its name suggests.

**Survivorship bias read as evidence.** The plan cited "all 164 jobs succeeded"
as an observation about system behaviour. Failed jobs had been deleted by hand.
Nothing about failure handling can be inferred from that sample. The
unresolved-reference finding survives only because it rests on the task
specifications rather than on the status column.

## Current design

Documents 01-14 have been updated in place to describe the system now being
built. This document is the record of what changed. Individual decisions are
recorded in [docs/adr](docs/adr/README.md); the evidence register remains
[gaps.md](gaps.md).
