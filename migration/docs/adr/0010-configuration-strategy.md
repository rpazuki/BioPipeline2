# ADR 0010: Configuration strategy

Date: 2026-09-10
Status: Accepted
Decision owner: Roozbeh Pazuki
Decision deadline: Before Phase 1 implementation
Related question: [Q10](../../13-open-questions.md)
Related gaps: G11

## Context

Decide configuration precedence, frontend-visible config, secret boundaries, and boot validation.

This ADR exists because the migration plan cannot safely proceed on this topic by implication. The linked gap row records the evidence from the current `bioPipeline` source tree; this document records the actual project decision.

## Options

- Option A: One `app_config.yaml` with environment profiles, as the current system has.
- Option B: Environment variables only.
- Option C: Layered: defaults, then an optional YAML file, then environment variables.

## Decision

**Option C**, implemented as [`app/settings.py`](../../../backend/app/settings.py).

Precedence is defaults, then an optional YAML layer keyed by environment
(`BP_CONFIG_FILE`, with the current system's `shared` plus per-environment
shape), then `BP_`-prefixed environment variables, which always win.

Secrets come from the environment only, never from the YAML layer, so the
config file is safe to commit and review. The browser-visible subset is an
explicit allowlist in `Settings.public()`, served at runtime so one image can
serve several deployments. `Settings.redacted()` logs the effective
configuration with secrets masked.

## Consequences

- Validation happens at import, so a missing or malformed required setting fails at boot rather than at the first request that needs it.
- A production environment refuses to start with development secrets, insecure cookies, CSRF disabled, or a wildcard CORS origin.
- A new setting is private to the server by default, because it is simply not named in the allowlist.

## Follow-up updates required

- Update `../../gaps.md` if this closes or supersedes a `Decision needed` row.
- Update `../../14-gap-closure-ledger.md` with the accepted decision and any implementation work created from it.
- Update the affected design document referenced by the gap row.
- Add implementation tickets, tests, or release notes if the decision changes v1 scope.
