# Frontend

Next.js App Router, TypeScript strict, TanStack Query, and a client generated
from the committed API contract.

```bash
make ui-setup            # install
make api                 # in another terminal: the backend on :8000
make ui                  # this app on :3000
make ui-check            # lint, types, tests, and the generated-client gate
```

## What it covers

Every screen here is backed by an endpoint the API actually serves. Nothing is
stubbed against a mock, because a screen built on a mock is a screen nobody can
trust.

| Screen | What it does |
| --- | --- |
| Sign in | Cookie session, lockout messages, per-field errors |
| Runs | Filter by status server-side; keyboard-operable rows |
| Run detail | Status, task progress, **deliveries**, submitted values, tasks, outputs, cancel |
| Pipelines | Cursor-paged list |
| Pipeline editor | Compile preview with located diagnostics, input contract, stage graph |
| Publications | Entries, with withdraw |
| Publication editor | Compose a catalog entry from a revision's bindable targets, with a live preview of the researcher's form |
| Catalog | Published entries, searchable |
| Catalog entry | A form rendered from the publication's fields, in the admin's words, with a confirmation step |
| Pipeline detail | Revisions, and a submission form generated from the revision's compiled contract |
| Schedules | What will run and when, said in words; compose one from a catalog entry; what each window actually did |
| Storage | The paths a task container may read: register one on an attestation, see which are working, withdraw one |
| Run detail | Tasks, each with what it printed — the tail, refreshed while it runs — plus outputs and deliveries |
| Account | Who you are; change password |

## What it does not cover, and why

These are absent rather than half-built. Each needs a backend endpoint that
does not exist yet:

- **Saved values, the type library, the environment and package browser, users
  and audit.** No endpoints.
- **Chunked upload.** The `upload_*` limits arrive in `/config` and nothing
  consumes them.

## Configuration

Two layers, and the split is deliberate.

**Runtime**, from `GET /api/v1/config` before anything renders — the API prefix,
the app name, the environment, the upload limits, and the CSRF header's name
and value. One build serves several deployments, and the CSRF header is
published rather than duplicated here so a client cannot drift from the server.

**Build time**, and only what cannot be anything else:

| Variable | Meaning |
| --- | --- |
| `NEXT_PUBLIC_API_ORIGIN` | Where the API is. Empty means same origin, which is the production shape. Set it in development, where the two are on different ports. |
| `NEXT_PUBLIC_BASE_PATH` | The path prefix. **Build time, not runtime** — Next bakes it into every asset URL and router link, so one image cannot serve two deployments mounted at different prefixes. |
| `NEXT_PUBLIC_API_PREFIX` | The bootstrap guess, default `/api/v1`. The server's own `api_prefix` is used for everything after the first call. |

`DEFAULT_API_PREFIX` in [`src/lib/config.ts`](src/lib/config.ts) is the only
place a version prefix is written down.

## The generated client

`src/generated/api-types.ts` is generated from `contracts/openapi.json` and
committed. `npm run generate:check` — part of `make ui-check` — fails if it is
stale, which is the same gate the backend applies to the contract itself, one
link further down the chain.

The client is a thin typed wrapper rather than a generated one
([`src/lib/client.ts`](src/lib/client.ts)). A generated client would have to be
taught the same four conventions anyway — the cookie, the CSRF header, the
error envelope, the request id — and the types already come from the contract,
which is where the safety is.

Status fields are unions, not strings, because the API publishes its
enumerations. A status added to the backend fails the typecheck here rather
than rendering as a blank badge.

## Decisions worth knowing

**The editor cannot compose an invalid binding.** Its targets come from the
revision itself, under the same rules the publish validates against — so the
only mistakes left to make are editorial, which is what the preview is for. The
preview renders the *same component* the catalog does, so it is the form rather
than an impression of it.

**Types are converted in the form, because nothing behind it can.** A control
hands back a string and the pipeline wants an integer. The published field type
is the first point in the system that knows which — the compiled IR carries no
scalar type for a public input, and the platform has no coercion step. So the
conversion happens on the way out, and a value that will not convert is
reported against its own field rather than sent and rejected.

**The submission form is generated, and generated from one source.** A
revision's stored `input_schema` is what the compiler produced for that exact
revision, and a revision is immutable — so the form cannot disagree with what
will run. It is not fetched until a submission dialog opens: a contract nobody
has asked to see is a request per table row for nothing.

**What the contract cannot say, the form does not invent.** There is no scalar
type for a `value` input — a public input is one whose default is
`$WILL_PROVIDE$`, so there is no default to infer a type from, and the
authoring format has no way to declare one. Those render as text and are sent
as strings. A `type_ref` names an entry in a type library no endpoint serves,
so those render as free text and the field says so rather than pretending to
be a typed editor.

**The editor does not validate YAML in the browser.** A browser-side schema
check would be a second implementation of the compiler's rules, and the moment
the two disagree the author believes the wrong one. The server compiles; this
renders what it said.

**An expired session does not redirect.** It raises a dialog over the page, so
a half-filled form survives it. Sessions last a week and tasks run for a day,
so this fires rarely and always at the worst moment.

**Polling, not streaming.** There is no event stream endpoint. A non-terminal
run is re-read every `LIVE_POLL_MS` (5s, in
[`src/lib/query-client.ts`](src/lib/query-client.ts)); a terminal one is not
polled at all.

**No optimistic updates on submit or cancel.** The server decides the run id,
and cancellation is a request rather than a result — showing "cancelled" before
the worker has stopped is a lie the next poll contradicts.

## Tests

`npm run test` — Vitest, jsdom, Testing Library. Only `fetch` is replaced, so
the real query client, API client and error handling are exercised.

`npm run e2e` — Playwright, against a real backend. See
[`playwright.config.ts`](playwright.config.ts) for what has to be running.
These cover what component tests cannot: that the cookie is accepted, the CSRF
header is the one the server wants, and the error envelope is shaped as this
client assumes.

## Accessibility

Targeting WCAG 2.1 AA. What is in place: labels associated with every control
and errors tied to them with `aria-describedby` and `aria-invalid`; a skip
link; `aria-current` on the active nav item; keyboard-operable table rows;
`<dialog showModal()>` so the browser supplies the focus trap; status regions
announced with `aria-live`; a status palette with contrast on both grounds;
`prefers-reduced-motion` honoured. Not yet done: an automated axe pass in CI,
and a manual audit.
