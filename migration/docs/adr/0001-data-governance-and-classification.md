# ADR 0001: Data governance and data classification

Date: 2026-09-10
Status: Accepted (amended 2026-09-10)
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 0 closes
Related question: [Q1](../../13-open-questions.md)
Related gaps: G66, G01

## Context

Decide whether the platform may hold human-derived or otherwise identifiable data, and what governance controls are mandatory.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: Treat the platform as holding a data corpus, with classification tiers, encryption at rest, DPIA sign-off and residency rules.
- Option B: Treat the platform as a conduit that holds no corpus, with transient handling and prompt cleanup instead.
- Option C: Design for identifiable human data now, in case it is used for that later.

## Decision

**Option B, with the absolute claim withdrawn.** "The platform holds no data"
was unsafe shorthand. It does store data; what it is not is a *system of
record*. The accurate statement:

> BioPipeline2 is not a system of record. It processes explicitly permitted
> classes of transient input and output data, retains operational metadata for
> provenance, and deletes artifact bytes according to policy.

While bytes exist, confidentiality, authorization, backup and
incident-response questions still apply — transience changes retention
obligations, it does not remove them. And a generic Python platform is
technically capable of receiving identifiable data even though today's
workflows do not.

Users supply inputs at run time; outputs are returned to them; nothing is
retained as a corpus. Run records, parameters and logs survive for provenance;
input and output bytes are removed by TTL cleanup (see ADR 0012).

The data is not domain-restricted and is not human-derived. The platform
executes arbitrary Python and the current pipelines process microbial growth
and metabolic-model data. There is no ethics or DPIA gate, no residency
constraint, and no encryption-at-rest mandate.

Artifact read auditing is nevertheless **kept on** (`artifact_access_events`,
`BP_AUDIT_ARTIFACT_READS=true`). It costs almost nothing, and retrofitting read
auditing later is expensive.

## Consequences

- Document 11's data-governance section is void; see [15-premise-correction.md](../../15-premise-correction.md).
- No approval gate blocks go-live.
- **To define before v1 ships:** the permitted and prohibited data classes; whether identifiable or controlled data is technically prohibited or merely unsupported; retention and redaction rules for parameters and logs, which are *not* covered by artifact TTL; and a review trigger before a publication may process a broader data class.
- Disk encryption provided by the VM or storage platform should be evaluated as a low-cost baseline, rather than declined on the grounds that the platform is not a corpus.
- The planned RNA-seq workload must be classified before it is implemented.
- If the platform is ever pointed at identifiable data, this ADR must be superseded before that happens, not after.
- Because nothing is retained, disk pressure is managed entirely by retention policy, which makes TTL cleanup load-bearing rather than hygiene.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
