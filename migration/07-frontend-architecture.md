# Frontend Architecture

## Goals

The frontend should feel like a focused workflow platform, not a collection of admin tools that grew over time. It should support two clear user journeys:

- Admins create, validate, publish, monitor, and operate workflows.
- Researchers discover published catalog entries, submit runs, manage schedules, and retrieve outputs.

## Stack

Recommended stack:

- Next.js App Router.
- TypeScript with strict mode.
- Generated OpenAPI client.
- TanStack Query for server state.
- React Hook Form with Zod or generated schema adapters for forms.
- A small design system with consistent tables, forms, dialogs, status badges, empty states, and log viewers.
- Playwright for critical workflows.
- Vitest and Testing Library for components and hooks.

## Folder structure

```text
frontend/src/
  app/
    (auth)/
    (admin)/
    (researcher)/
    api-health/
  features/
    auth/
    pipelines/
    pipelines/
    publications/
    catalog/
    runs/
    schedules/
    types/
    artifacts/
    admin/
  components/
    layout/
    ui/
    forms/
    data-table/
    log-viewer/
  generated/
    api-client.ts
    api-types.ts
  lib/
    query-client.ts
    route-policy.ts
    config.ts
```

Feature folders should own their API hooks, page components, form components, and tests.

## Navigation model

### Admin navigation

- Dashboard.
- Pipelines (one level; there is no separate Workflows section).
- Publications.
- Runs.
- Type Library.
- **Environment** — installed packages, callable search, signatures, install
  history, snapshots. This is a primary authoring surface, not an admin
  afterthought: in a generic Python executor it is how an admin discovers what
  can be called at all.
- Users.
- Audit and Operations.

### Researcher navigation

- Catalog.
- My Runs.
- My Schedules.
- Saved Values.
- Account.

Avoid showing implementation terms like queue internals unless the user is in an admin operations page.

## Server state

Use TanStack Query for all server-backed state:

- List pages use query keys by feature, filters, page, and sort.
- Mutation success invalidates specific queries.
- Long-running run pages subscribe to event streams and also refetch on reconnect.
- Avoid manually keeping many duplicated local arrays in page components.

Example query keys:

```text
['catalog', filters]
['publication', publicationSlug]
['run', runId]
['run-tasks', runId]
['pipeline-revision', revisionId]
['type-library']
```

## Forms and schemas

Researcher submission forms should be generated from publication field specs, but not as an opaque generic form. Use schema-driven rendering with field-specific components:

- Primitive input.
- Enum and multi-enum selectors.
- File upload picker.
- Shared storage browser.
- Directory selector.
- Typed object editor.
- Saved value chooser.
- Output destination picker if exposed.

Admin forms should expose workflow and publication concepts clearly:

- Pipeline source editor.
- Validation diagnostics panel.
- Compiled input contract preview.
- Publication field editor.
- Catalog preview.
- Test submission preview.

## Page responsibilities

A page component should coordinate layout and feature components. It should not implement domain operations directly.

Good pattern:

```text
app/(admin)/pipelines/[id]/page.tsx
  renders PipelineDetailScreen

features/pipelines/PipelineDetailScreen.tsx
  coordinates tabs and selected revision

features/pipelines/usePipeline.ts
  owns queries and mutations

features/pipelines/components/PipelineRevisionEditor.tsx
  focused editor component
```

## Run detail UX

Run detail should be the operational center for researchers and admins.

Core sections:

- Summary: status, publication, submitted by, start/end time, **environment
  snapshot**, and queue position while queued. With tasks that can run for a
  day, "when will this start" is as important as "did it work".
- **Deliveries**, separately from outputs: a shared-storage delivery can fail
  after the run succeeded, and must be visible and retryable.
- Submitted values.
- Task graph with status.
- Logs by task attempt.
- Inputs and outputs.
- Artifacts and downloads.
- Retry/cancel actions when allowed.
- Audit/events timeline.

Admins see more operational details; researchers see enough to understand progress and retrieve results.

## Catalog UX

The catalog should be fast to scan and safe to submit from:

- Search and filter by domain, tag, owner, and status. Backed by trigram
  indexes on publication title and description.
- Clear indication of required inputs.
- Submission form with validation before upload-heavy operations where possible.
- Draft saving for long forms.
- Confirmation screen summarizing values before run creation.
- Link to created run immediately after submission.

## Admin publication UX

Publishing should be treated like releasing a product version:

1. Select pipeline revision.
2. Review compiled inputs and outputs.
3. Configure public field labels, defaults, source policy, and grouping.
4. Preview researcher form.
5. Run a test submission if possible.
6. Publish a new publication revision.

Do not let the publication editor patch arbitrary YAML paths. It should configure the public contract for an already compiled pipeline revision.

## Design system rules

Define shared components early:

- Status badges for run, task, publication, validation.
- Data table with sorting, filtering, pagination, and column persistence if needed.
- Form field layout and validation messages.
- Code/YAML editor wrapper.
- File upload component.
- Log viewer with search and download.
- Confirmation dialogs for destructive actions.
- Empty states with direct actions.

## Frontend tests

Minimum tests:

- Login and session recovery.
- Catalog listing and submission form validation.
- Run detail state transitions.
- Admin workflow validation and publication preview.
- Type editor for structured values.
- Path prefix deployment smoke test.

Use API mocks for component tests and a seeded backend for Playwright end-to-end tests.


## Review additions

> Findings below are registered with evidence, severity, and status in
> [gaps.md](gaps.md). This section says what to do about them.

### Screens implied elsewhere but missing from the navigation

The admin navigation omits surfaces that exist today or that the new backend
requires:

- **Pipeline / workflow template gallery.** The current system has a template
  catalog for pipelines and job definitions; nothing in this document replaces it,
  yet a blank YAML editor is a poor starting experience.
- **Package / function browser.** Admins currently discover callable science
  functions by listing and searching installed packages and reading signatures.
  Under immutable images this becomes "browse what is inside this runtime
  environment" - and without it, authoring loses its discovery step.
- **Runtime environment detail**: which image digest, what it contains, health,
  which publications use it, and how to promote or roll back.
- **Backup / restore**, if it stays an in-app admin feature.
- **AI Designer**, if that subsystem is carried.
- **Deliveries** on the run detail page - an output that failed to reach shared
  storage must be visible and retryable.
- **Quota and usage**, for both the researcher ("you are using X of Y") and the
  admin, once resource governance exists.

Each of these is a decision in
[10-feature-parity-and-scope.md](10-feature-parity-and-scope.md); the navigation
model should reflect whichever way they go rather than omitting them silently.

### Large file upload UX

The form component list has a "file upload picker" and nothing else. For
multi-gigabyte genomics inputs the upload *is* the experience:

- Chunked upload with visible progress, pause, resume across a page reload, and
  cancel that actually aborts the server-side upload.
- Client-side checksum where feasible, and a clear error when the server's
  checksum disagrees.
- Guidance toward shared-storage selection when a file is above a threshold -
  browsing an already-mounted path beats uploading a copy.
- Validate the rest of the form **before** the upload starts, not after. Document
  07 already hints at this; make it a hard rule.
- A submit flow that survives a dropped connection mid-upload.

### Server state details the plan leaves open

TanStack Query is the right choice, but the hard parts are unaddressed:

- **Polling versus SSE fallback.** The event stream is described as a convenience;
  state the polling interval used when it is unavailable, and how the two are
  reconciled without double-fetching.
- **Log streaming** for a task producing thousands of lines a second:
  virtualisation, a cap on retained lines in memory, and a "download full log"
  path rather than rendering it all.
- **Optimistic updates**: which mutations use them. For run submission, none -
  the server decides the run id.
- **`If-Match` / ETag** handling for admin edits, matching the concurrency control
  added to [05-api-and-contracts.md](05-api-and-contracts.md); a `409` must
  produce a usable "someone else changed this" experience, not a toast.
- **Auth expiry**: what happens when the session expires mid-form. Losing a long
  submission form to a redirect is a guaranteed complaint.

### Accessibility, and it is easier now than later

Not mentioned anywhere in the plan. For an institutional deployment this is
usually a procurement requirement, and retrofitting a data-table and a form
system is expensive:

- Target WCAG 2.1 AA. Keyboard operability for tables, dialogs, and the
  file/shared-storage browser. Labels and error association on every field.
  Focus management in dialogs. Status changes announced to screen readers.
  Contrast that survives the status-badge palette.
- Automate what can be automated in CI and record the rest as a manual checklist.

### Other gaps

- **Error and empty states as a system**, including a page-level error boundary
  and a consistent way to render the backend's structured error `details` -
  field-level validation errors from document 05 must land on the right inputs
  automatically.
- **Time zones**: display runs and schedules in a stated zone with an explicit
  label. Scientific scheduling across a DST boundary is a real source of
  confusion.
- **Browser support** statement, and behaviour without JavaScript for the login
  page at minimum.
- **Path prefix**: every asset, API call, redirect, and cookie path must respect
  the configured base path. Document 07 lists a smoke test for it; also state
  that no absolute `/api/v1` string may be hard-coded.
- **Build and runtime config**: whether one frontend image can serve multiple
  deployments (which requires a runtime config endpoint) or is built per
  environment.
- **YAML editor** choice, and whether it validates against the workflow schema in
  the browser or relies solely on the server's compile-preview diagnostics.

## What is built

The application in [`frontend/`](../frontend/README.md) follows this document
where the API can back it, and stops where it cannot. The rule applied
throughout: **no screen is built against a mock.** A researcher who finds a
catalog page that cannot submit anything has learnt not to trust the rest.

Built: the role-based shell, sign-in with per-field errors and lockout
messages, Runs with server-side status filtering, Run detail (status, task
progress, deliveries, submitted values, tasks, outputs, cancel), Pipelines,
the pipeline editor with compile-preview diagnostics and the compiled input
contract, revisions with submission, and Account.

The submission form **is** schema-driven, ahead of publications: it is
generated from the revision's stored `input_schema`, which is what the compiler
produced for that exact revision. Field-specific components arrive as the
contract gains the vocabulary for them — a shared-storage browser when there is
an endpoint to browse, an upload picker when there is somewhere to upload, an
enum selector and a typed object editor when the type library is served. What a
publication adds on top is editorial: relabelling, grouping, defaults, and
deciding which fields a researcher sees at all.

The catalog is built: published entries, a form rendered from the publication's
fields in the admin's words and grouping, a confirmation step that repeats the
values back before spending a day of compute, and per-field errors from the
server landing on the field that caused them. Field-specific controls arrive as
the contract gains the vocabulary for them — a shared-storage browser when
there is an endpoint to browse, an upload picker when there is somewhere to
upload, an enum selector when constraints are published.

The publication editor is built, and is the "releasing a product version" flow
this document describes: pick a revision, see everything in it a field could
attach to with the value it holds today, choose what to expose, name it, watch
the researcher's form compose itself, and publish. It cannot produce an invalid
binding — the targets come from the revision under the same rules the publish
validates against — so the mistakes left to make are editorial, which is what
the preview is for.

Not built: schedules, saved values, the type library, the environment and
package browser, users and audit, log streaming, artifact download, and chunked
upload.

### Answers to the questions this document left open

- **Stack.** Next.js App Router, TypeScript strict, TanStack Query, and a
  `openapi-typescript` client generated from the committed contract, gated for
  freshness in `make ui-check`. No form library: the forms here are small, and
  a dependency that renders three fields is not worth the second validation
  vocabulary.
- **Polling versus SSE.** Polling, because there is no event stream endpoint.
  The interval is one constant, `LIVE_POLL_MS` (5s), and a terminal run is not
  polled at all.
- **Optimistic updates.** None on submit (the server decides the run id) and
  none on cancel (cancellation is a request, not a result; the worker holding
  the task may take a while to stop, and a premature "cancelled" is a lie the
  next poll contradicts).
- **Auth expiry mid-form.** A dialog over the page, never a redirect. The page
  keeps its state, so a half-filled submission survives.
- **YAML editor.** A plain textarea, and the browser does **not** validate the
  document. A client-side schema check would be a second implementation of the
  compiler's rules, and when the two disagree the author believes the wrong
  one.
- **Build versus runtime config.** The API prefix, app name, environment,
  upload limits, and the CSRF header come from `GET /api/v1/config` at boot,
  so one build serves several deployments. The **path prefix cannot**: Next
  bakes it into every asset URL and router link, so it is a build input and
  that limitation is stated rather than papered over.
- **Time zones.** Every timestamp carries its zone explicitly.
- **Error `details` onto fields.** `details.errors[].path` is matched against
  the form's known fields; anything unmatched is shown rather than dropped, so
  a form cannot refuse to submit and say nothing.
- **Accessibility.** Targeting WCAG 2.1 AA, with the structural parts done and
  the automated axe pass and manual audit still to do.

### A gap the form exposed

**A `value` input has no declared scalar type.** An input is public precisely
because its default is `$WILL_PROVIDE$`, so there is no default to infer a type
from, and `InputPolicy` has no field to declare one. The compiled contract
therefore carries only `accept: file | directory | value`.

The consequence is that a submitted `"4"` stays the string `"4"` all the way
into a science function that expected an integer.
`materialise.coerce_value` exists for exactly this, and its docstring says so —
"Submissions arrive from HTML forms, so numbers arrive as strings. Coercing
here, and failing loudly, is what stops a string reaching a science function
that expected a number" — but **nothing calls it**, because nothing can supply
its `target` argument. It is a guarantee written down and not provided.

Closing it means adding a type to `InputPolicy` (`threads: {accept: value,
type: integer}`), which changes the authoring format and so wants an ADR. Until
then the form renders text fields and this document records why.

### Still open

- `If-Match` / ETag handling: the API does not implement optimistic
  concurrency on any resource yet, so there is nothing to handle.
- Large-upload UX in full — chunking, resume, checksum disagreement, and
  steering a multi-gigabyte input towards shared storage instead — is the
  largest single piece of frontend work remaining, and it needs the upload
  endpoints first.
- Behaviour without JavaScript, and a stated browser-support floor.
