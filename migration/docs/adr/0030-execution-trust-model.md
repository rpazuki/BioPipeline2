# ADR 0030: Execution trust model

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Related gaps: G61, G62

## Context

The platform executes arbitrary Python. Whether task containers are a security
boundary or resource hygiene depends entirely on who can cause code to run, and
document 06 specified hardening without settling that question.

## Options

- Option A: Admins only author pipelines; researchers supply parameters to vetted forms.
- Option B: Defence in depth — admins are legitimate but blast radius is still limited.
- Option C: Assume pipeline authors may be hostile; full sandboxing.

## Decision

**Option A.** Code execution is admin-authored and trusted. Researchers can only
supply values to forms an admin published.

Containers therefore exist for resource limits, timeouts, dependency isolation
and crash isolation — **not** to contain an attacker. No seccomp profiles, no
user-namespace work, no escape-vector review.

One distinction is kept sharp: **code is trusted, researcher input is not.**
Researchers supply file paths, shared-storage selections and URLs. Path
containment, input validation and the SSRF controls on `url` inputs remain
exactly as strict as if the whole system were hostile.

## Consequences

- A large slice of document 06's container-hardening guidance is removed.
- The task contract still refuses credential-shaped environment variables, and a test asserts no platform secret is visible inside a task container. That is cheap and guards against mistakes rather than attackers.
- Uploaded archive handling still rejects absolute paths, `..` components and outward symlinks: researcher-supplied data, not admin code.
- If pipeline authorship is ever opened beyond admins, this ADR must be superseded first.

## Follow-up updates required

- Update `../../gaps.md` rows G61 and G62 to reflect the narrowed scope.
- Update document 06's security section.
