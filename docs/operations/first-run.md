# Setting up an empty deployment

A freshly deployed BioPipeline2 has a database, five running processes and
nothing else: no science code, no storage, no pipelines, no catalog. This is
the path from there to a researcher submitting a run, in the order the
dependencies actually fall.

Everything here is done by an administrator. Installing it is
[deployment.md](deployment.md); this is the day after.

| Step | What it gives you | Can you skip it? |
| --- | --- | --- |
| 1. Sign in, change the password | an account that is yours | No |
| 2. Add the people | accounts for researchers | Until somebody else needs in |
| 3. Science code into an environment | `labUtils` and friends importable | No |
| 4. Register shared storage | reading the lab's shares, delivering to them | Only if everything is uploaded |
| 5. Component library and pipeline | an immutable revision that compiles | No |
| 6. Publish it | a catalog entry with a form | Only if admins are the only users |
| 7. Run it | proof the whole path works | No |

The worked example throughout is the OD600 growth-rate pipeline, which is the
one shipped in [`examples/`](../../examples/pipelines/od600_growth_rates.yaml).

## 1. Sign in and change the password

The deployment created **two** accounts, not one: `scripts/dev/seed.py` makes
a seeded administrator and a seeded researcher, and unless you set
`BP_SEED_RESEARCHER_PASSWORD` separately, the researcher has the *same*
password as the administrator.

So, in this order:

1. Sign in at `https://<host>/` as the seeded administrator and change the
   password. The seeded one has been in a shell history and an environment
   variable.
2. **Admin → Accounts**, find the seeded researcher
   (`researcher@example.org` unless you renamed it) and either deactivate it
   or reset its password. It exists so an empty deployment can be driven
   end to end; leaving it with the administrator's password is a second
   account nobody is watching.

Every account you create afterwards gets a generated one-time password
instead, and the platform refuses that session anything except changing it.

## 2. Add the people

**Admin → Accounts → New account.** Email, display name, role.

- **Researcher** — browses the catalog, submits, sees their own runs.
- **Administrator** — all of that, plus authoring, publishing, environments,
  storage, accounts and the audit.

The screen shows a one-time password **once**. It cannot be fetched again;
reset the account if it is lost. Hand it over out of band — not in the same
email as the link.

You can leave this until later. Nothing else in this guide needs a second
account.

## 3. Get the science code in

This is the step with real choices, so it is the longest section.

A task container carries the runner and the standard library and nothing else
(ADR 0028). `labUtils` has to reach it by one of three routes.

### Route A — an environment and `pip install` (the normal one)

**Environments → New environment.** Name it — `lab`, say. The **first**
environment is made the default automatically, and a run pins the default
unless something says otherwise; a second one is not, and
`POST /api/v1/environments/{id}/default` is what moves the pointer.

Creating it builds an empty virtualenv inside the task image — a minute or
two, and the request waits, because a build that reports success before it
finished would be worse.

Then **Install a package**:

```text
pandas==2.2.1
numpy>=1.26,<2
scipy
labUtils==0.4.0
matplotlib[all]==3.8.4
```

Accepted: a package name, optional extras in brackets, an optional version
specifier. That is all — the box takes **a requirement, not a command line**:

```text
-e /srv/labUtils                      refused
--index-url https://pypi.internal/    refused
git+https://github.com/rpazuki/lab_utils.git   refused
labUtils @ git+https://github.com/...          refused
```

with *"Flags, paths and URLs are not accepted here"*. An install runs as an
administrator inside the platform's own container, and a specifier carrying
`--index-url` would be an install nobody reviewed.

Each install builds the **next generation** of the environment out of place
and moves a pointer when it succeeds. Anything already running keeps the
generation it pinned, so you can install at four in the afternoon without
disturbing a task that started on Tuesday. The **Generations** list on the
environment screen shows every build, which one new runs pin, and which have
been reclaimed.

**If `labUtils` is on an index** — PyPI, or an institutional index the host is
configured to reach — Route A is the whole story, and it is the only route
that gives a reproducible record: a version number anyone can reinstall.

### Route B — a clone on the host, mounted into every task (the GitHub route)

The lab's `labUtils` lives in a Git repository, not on an index. The old
system installed it with
`pip install "labUtils @ git+https://github.com/rpazuki/lab_utils.git#subdirectory=src"`,
and **this platform refuses that specifier** (see above).

What works today is a directory the platform mounts read-only into every task
container and puts on `PYTHONPATH`:

```bash
sudo -u biopipeline git clone https://github.com/rpazuki/lab_utils.git \
    /var/lib/biopipeline2/libraries/lab_utils
```

```bash
# /etc/biopipeline2/biopipeline2.env
BP_TASK_LIBRARY_PATHS=["/var/lib/biopipeline2/libraries/lab_utils/src"]
```

```bash
sudo systemctl restart 'biopipeline2-worker@*'
```

Point at the directory that *contains the importable package* — for a
`src/`-layout repository that is `…/src`, the directory with `labUtils/` in it.

What this costs you: the mount is a working tree, so **a run using it cannot
be reproduced from its own record**. The platform says so rather than
pretending otherwise — a generation containing a working-tree install is
marked, and so is every run that pins it. Updating the code is
`git pull` plus a worker restart, and nothing records which commit a given run
used. Pin a tag and write the tag in the environment description if that
matters.

> **Not supported, and worth deciding.** Installing straight from a Git URL —
> the thing the old system did — would need `check_specifier` to accept
> `git+https://` for an allowlisted set of hosts. It is a small change and a
> real security decision, because it turns an install box into "fetch and run
> code from the internet". Nobody has made that decision; until somebody does,
> Route B is the GitHub answer.

### Route C — install into the host, for an editable working tree

An administrator with shell access can install a working tree into a
generation directly. Do this only when someone is actively developing
`labUtils` against the platform: the generation is then unreproducible *and*
mutable, which is the combination ADR 0028 exists to avoid. The platform
detects it (`pip list` reports `editable_project_location`) and marks every
run accordingly.

### Check it before trusting it

On the environment screen, **What a pipeline can call**: leave the module box
empty to list what is importable, or type `labUtils.media_bot` to read the
functions and signatures. If `labUtils` is not in that list, no pipeline
naming it will run, and this is where you find out — not in a failed run at
3 a.m.

## 4. Register the lab's storage

Skip this only if every input is uploaded through the browser and every output
is downloaded through it.

**Storage → Register root.**

| Field | Example | Notes |
| --- | --- | --- |
| `id` | `lab-share` | What a pipeline writes in `shared_root:` |
| `label` | `Geoff Lab share (read-only)` | What researchers see |
| `root_path` | `/mnt/labshare/geoff` | Absolute, must exist on the worker host |
| `attestation_note` | `Checked 2026-10-30 with ICT: the service account is a member of geoff-lab-ro; the share is already readable by every member of the group.` | Required, and the point of the whole screen |
| `readable` / `writable` | `true` / `false` | Writable only where delivery is meant to land |

Tasks read shared storage as the platform's service account, not as the
researcher (ADR 0013). The platform cannot check what that account may see, so
the attestation records *what a person checked*: which share, whose members,
against which access list. The database refuses to hold a root without one.

Paths are refused if they are relative, if the platform cannot see the
directory, or if they overlap its own storage — which would hand every task a
read-only view of every other run's outputs.

Revoking a root withdraws it rather than deleting it: a delivery that went
there still names it, and anything already running keeps the mount it was
given.

## 5. The component library and the pipeline

### The library file

Reusable graphs of calls live in `BP_COMPONENT_LIBRARY_ROOT`
(`/var/lib/biopipeline2/components`), one YAML file each:

```bash
sudo -u biopipeline cp growth_rates.yaml /var/lib/biopipeline2/components/
```

A pipeline then imports it by filename. Both library shapes load; see
[the authoring reference](../authoring/pipeline-format.md#components-and-component-libraries).

### The pipeline document

**Pipelines → New revision.** Paste the YAML, press **Compile preview** and
read the diagnostics: the preview stores nothing, and a revision is immutable
once stored, so this is where mistakes are cheap.

The format, every key, and what the compiler refuses are in
[docs/authoring/pipeline-format.md](../authoring/pipeline-format.md). The
shortest document that does something real:

```yaml
pipeline: od600_growth_rates
title: OD600 growth rates
defaults:
  data_root: $WILL_PROVIDE$
  od600_col: od600
  moving_window_size: 5
inputs:
  data_root:
    accept: directory
    sources: [shared, upload]
    help: Folder holding the plate-reader exports.
stages:
  - name: fit
    steps:
      - name: df_parsed
        package: labUtils.media_bot
        method: parse
        parameters:
          raw_data: "{data_root}"
          value_column_name: "{od600_col}"
    outputs:
      results:
        path: "processed/fit"
        delivery: [download]
        retention_days: 90
```

Store it. The revision is now permanent and versioned; editing means a new
revision, and runs keep pointing at the one they used.

## 6. Publish it as a catalog entry

A revision is not visible to researchers. A **publication** decides which of
its values become form fields and what each one is called.

**Publications → New publication**, then five steps on one screen: choose the
revision, describe the entry, choose what to expose, see the form a researcher
will see (the real component, not an impression of it), publish.

### What you can bind a field to

| Target | Names | Use it for |
| --- | --- | --- |
| `default_value` | a `$WILL_PROVIDE$` public input | the experiment folder, the sample sheet |
| `step_parameter` | stage + step + parameter | the moving window of the fit |
| `stage_input` | stage + input key | pointing one stage at a different file |
| `stage_output` | stage + output key | *stored, but delivery does not read it yet — the screen warns* |

A field names a **stage**, not a stage key: with a matrix, exposing the fit
stage's window exposes it for every matrix row. Binding to a `default_value`
that is not `$WILL_PROVIDE$` is refused at publish time, with a message saying
where the value really lives — a plain default was substituted at compile time
and no longer exists in the revision.

### The field properties

The screen offers six per field: **expose**, **Label**, **Help text**,
**Type**, **Group**, **Required**. The API accepts more, and today the API is
the only way to set them:

| Property | Values | What it does |
| --- | --- | --- |
| `key` | `experiment_folder` | What the submission is keyed by |
| `label` | `Experiment folder` | The control's label |
| `field_type` | `string`, `integer`, `number`, `boolean`, `enum`, `file`, `directory`, `url`, `object`, `array` | The control, and the coercion applied before anything runs |
| `required` | `true` / `false` | Whether the form will submit without it |
| `help_text` | `One folder per plate reader export.` | Under the control |
| `placeholder` | `/mnt/labshare/geoff/2026-03` | Inside the empty control |
| `ui_group` | `Inputs`, `Fitting`, `Advanced` | Groups controls under a heading |
| `order_index` | `0`, `1`, `2` | Order within the group |
| `default_value` | `5` | Pre-filled, and changeable |
| `fixed_value` | `od600` | Applied and **not** shown as editable |
| `visibility` | `visible`, `hidden`, `readonly` | `hidden` + `fixed_value` is how you pin a value without showing it |
| `type_ref` | `CustomReplicateRule` | A name from the document's `definitions`; the schema is snapshotted at publish |
| `saveable` | `true`, `false`, unset | Whether a researcher may keep the value and reuse it. Unset means "if it is typed" — a five-key rule object is worth keeping, a thread count is not |
| `source_policy` | `{"sources": ["shared", "upload"]}` | Which sources a file field offers |
| `delivery_policy` | `{"shared_root": "lab-share"}` | Recorded; delivery does not consult it yet |

A complete request, with one field of every kind:

```bash
curl -X POST https://<host>/api/v1/publications/revisions \
  -H 'content-type: application/json' \
  -H 'X-Requested-With: BioPipeline2' \
  -b "$COOKIE" -d '{
  "slug": "od600-growth-rates",
  "pipeline_revision_id": "'"$REVISION"'",
  "title": "OD600 growth rates",
  "description": "Parse plate-reader exports and fit growth curves.",
  "fields": [
    {
      "key": "data_root",
      "label": "Experiment folder",
      "binding": {"target": "default_value", "binding_key": "data_root"},
      "field_type": "directory",
      "required": true,
      "help_text": "One folder per plate-reader export, with its metadata beside it.",
      "placeholder": "/mnt/labshare/geoff/2026-03",
      "ui_group": "Inputs",
      "order_index": 0,
      "source_policy": {"sources": ["shared", "upload"]}
    },
    {
      "key": "mapping_yaml",
      "label": "Mapping file",
      "binding": {"target": "default_value", "binding_key": "mapping_yaml"},
      "field_type": "file",
      "required": true,
      "ui_group": "Inputs",
      "order_index": 1,
      "source_policy": {"sources": ["upload"]}
    },
    {
      "key": "moving_window_size",
      "label": "Moving window size",
      "binding": {
        "target": "step_parameter",
        "stage": "fit",
        "step": "df_fit_max_growth_rate",
        "binding_key": "moving_window_size"
      },
      "field_type": "integer",
      "required": false,
      "default_value": 5,
      "help_text": "Points per window when fitting the maximum growth rate.",
      "ui_group": "Fitting",
      "order_index": 2
    },
    {
      "key": "od600_col",
      "label": "OD600 column",
      "binding": {
        "target": "step_parameter",
        "stage": "fit",
        "step": "df_parsed",
        "binding_key": "value_column_name"
      },
      "field_type": "string",
      "fixed_value": "od600",
      "visibility": "hidden"
    },
    {
      "key": "replicate_rule",
      "label": "Replicate rule",
      "binding": {
        "target": "step_parameter",
        "stage": "fit",
        "step": "df_combined",
        "binding_key": "custom_rules"
      },
      "field_type": "object",
      "type_ref": "CustomReplicateRule",
      "saveable": true,
      "ui_group": "Advanced",
      "order_index": 3
    },
    {
      "key": "raw_data",
      "label": "Raw data file",
      "binding": {"target": "stage_input", "stage": "fit", "binding_key": "raw_data"},
      "field_type": "file",
      "required": false,
      "visibility": "readonly"
    }
  ]
}'
```

Then publish the revision:

```bash
curl -X POST "https://<host>/api/v1/publications/$PUBLICATION/publish?revision_id=$PUB_REVISION" \
  -H 'X-Requested-With: BioPipeline2' -b "$COOKIE"
```

Creating a revision and publishing it are separate on purpose: you can build
one, look at the form it produces, and only then make it the one researchers
see. Publishing is recorded in the audit — six months later, "which revision
was live in March" is a question somebody asks.

### Values a researcher can keep

A field marked `saveable` lets a researcher name what they filled in and reuse
it. The saved value carries the type schema it was saved against, so a
definition that changes later cannot quietly change what the saved value
means; one that no longer fits is refused with the reason rather than
submitted.

## 7. Run it

Two ways, and the difference matters:

- **Catalog → the entry → fill the form → Submit.** What a researcher does,
  and what you should test with.
- **Pipelines → the revision → Run.** Administrators only, for a revision you
  have just written and not yet published. Such a run records
  `requested_from = 'admin'`, so "which runs bypassed a publication" stays
  answerable.

Watch it on the run page: tasks, their statuses, the log of each attempt, the
outputs with their download links, and any shared delivery with the path it
landed at. A run that fails says which task, which step, and what the container
printed.

### Schedules, if the work is recurring

**Schedules → New schedule** composes the same form, stores the values, and
submits an ordinary run on its own clock. Every window it fires is an
ordinary run, with the same provenance.

## 8. Check the deployment is healthy

**Admin → Fleet → Right now** is the panel to look at: waiting work and the
age of the oldest queued task, live and quiet workers, overdue schedules,
stopped deliveries, free disk. [monitoring.md](monitoring.md) says which
numbers are worth an alert.

Once a week, or after anything unusual:

```bash
sudo -u biopipeline /opt/biopipeline2/.venv/bin/python \
  /opt/biopipeline2/scripts/ops/reconcile.py
```

## When the first run fails

**"No environment has been created."** Step 3. Without a default environment a
task runs against the image alone — the runner and the standard library.

**`ModuleNotFoundError: labUtils`.** The environment does not have it, or the
mounted library path points one directory too high. Check **What a pipeline
can call** on the environment screen; it answers from inside the container.

**The task stays queued.** No worker is running, or every task requests more
than the admission budget allows (`BP_WORKER_BUDGET_*`). The budget is the
second thing to check and the first thing people forget.

**`Permission denied` writing `/work` or `/env`.** The container is running as
a different user from the one that owns the directory. See
[deployment.md](deployment.md#when-it-does-not-work).

**"Input is outside every storage root this worker exposes."** The run named a
path that is not under a registered root. Step 4 — and the message names what
is missing rather than reporting a missing file from inside the container.

**A binding was refused at publish.** The message says what the revision
actually contains: a step that does not exist, a parameter that is not there,
or a default that was substituted at compile time. The coordinates come from
the compiled revision, so what it suggests is what is really there.

**An install fails.** The history on the environment screen keeps failed
installs with pip's own words — that is what it is for. A missing system
library, a wheel that needs a compiler, or a package name that does not exist
all look different there.

## Related

- [pipeline-format.md](../authoring/pipeline-format.md) — the YAML, every key, every refusal.
- [deployment.md](deployment.md) — installing the platform on a clean VM.
- [monitoring.md](monitoring.md) — what to watch and when to worry.
- [backup-and-restore.md](backup-and-restore.md) — before you have data worth losing.
