# ADR 0013: Shared storage authorization boundary

Date: 2026-09-15
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 storage design
Related question: [Q13](../../13-open-questions.md)
Related gaps: G63

## Context

Decide whether shared storage operations act as the requesting user or as a service account, and what controls compensate.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## The problem

A shared root is institutional storage -- in the current deployment a mapped
drive such as `H:/ROBOT_SCIENTIST/E_coli`, which on Linux becomes an NFS or
CIFS mount. When a researcher selects a folder there as input, or an output is
delivered back to it, something has to authenticate to that file server.

If the platform reads as a service account that can see more than the
requester can, it is a **confused deputy**: it holds authority the requester
does not, and acts on their behalf without checking whether they should have
it. Path containment does not help, because the escape is not *out of* the
root -- it is *within* it. Writes have the mirror problem: outputs land owned
by the service account, so the share's own permissions are bypassed and the
filesystem loses all attribution.

## Options

- Option A: A single service account, mounted once. Simple, and a
  privilege-escalation path exactly to the degree that users have unequal
  access to the exposed roots.
- Option B: Act as the requesting user -- per-user Kerberos tickets or mounts,
  delegation to the file server, uid mapping into containers. Correct by
  construction and weeks of work with ongoing operational burden.
- Option C: A service account, with the exposed roots constrained so that it
  grants nothing extra.

## Decision

**Option C.**

A root may be exposed only if **every platform user who can reach it already
has equivalent access to it**. The service account is then a shared identity
within a group that already shares, so there is no authority to confuse.

This is not a relaxation of the boundary; it relocates it. Separation between
labs is preserved because a root is exposed only within the project whose
members already share it -- a lab's group share is reachable by that lab, and
by nobody else. What Option C gives up is separation *within* a group that has
none on the filesystem anyway.

Enforced rather than assumed:

1. `shared_storage_roots.identity_mode` records the choice per root.
2. A `service_account` root must carry an explicit **attestation** -- who
   confirmed that the root is group-accessible, and when. An unattested root
   is not exposed, enforced by a check constraint rather than by convention.
3. Every read from and write to a shared root is audited **with the requesting
   user**, recovering in the database the attribution the filesystem loses.
4. A root that cannot honestly be attested is not exposed at all. That is the
   whole mechanism: the answer to a per-person tree is to leave it out, not to
   reach into it as somebody else.

## Consequences

- Shared-storage input selection and output delivery are unblocked, which they
  were not while this was open.
- The attestation is a human judgement the platform cannot verify. It is
  recorded with an actor and a timestamp so that it is at least accountable,
  and it should be re-checked when a root's permissions change.
- If a future root genuinely needs per-user separation, this ADR must be
  superseded by Option B before that root is exposed. Adding it to the
  allowlist under the current decision would be the privilege escalation this
  ADR exists to prevent.
- RNA-seq sharpens the question: sequencing-facility output is often delivered
  per project with tighter permissions than a lab share, so each such root
  needs its own attestation rather than inheriting one.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
