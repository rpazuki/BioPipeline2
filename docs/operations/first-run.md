# Set up the first pipeline

Complete these steps after [deploying BioPipeline2](deployment.md).
Use an administrator account in the browser and an account with `sudo` access
in a secure shell (SSH) session on the server. Run the Bash commands on the
server. Stop at a failed command and resolve its error before continuing.

The commands assume the application checkout is `/opt/biopipeline2`, the service
account is `biopipeline`, and the configuration file is
`/etc/biopipeline2/biopipeline2.env`. Substitute your deployment's paths and
account if different. Open the application's full address, including its port,
in the browser.

## 1. Sign in

1. Open the application and sign in as an administrator.
2. Open **Account** and change any temporary or shared initial password.
3. If development accounts were created with `scripts/dev/seed.py`, open
   **Administration → Accounts**. Deactivate unused accounts or reset their
   initial passwords.

## 2. Create researcher accounts

Skip this section if you will test with your administrator account.

1. Open **Administration → Accounts → New account**.
2. Enter the person's email address and display name.
3. Select the researcher role. Select administrator only for someone who will
   manage the application.
4. Create the account.
5. Copy the one-time password displayed on screen and give it privately to the
   person. Ask them to sign in and change it.

## 3. Prepare the Python environment

### 3.1. Create or select an environment

1. Open **Environments**.
2. Select an existing environment, or click **New environment**, enter a name
   such as `lab`, and wait for creation to finish.
3. Confirm that the environment intended for new runs is marked **default**.
   The first environment created becomes the default automatically.

### 3.2. Install packages

1. Enter `pandas==2.2.1` in **Install a package** and click **Install**.
2. Wait until its entry in **History** says **succeeded**.
3. Enter `numpy>=1.26,<2` and click **Install**.
4. Wait until its entry in **History** says **succeeded**.
5. Read the dependency list for the Python functions you intend to run, in the
   library's package configuration or installation instructions. Install those
   dependencies one requirement at a time.
6. Confirm the packages and versions appear under **Installed**.

Enter package requirements only, such as `scipy` or `matplotlib==3.8.4`.
Do not enter a `pip install` command, a directory, an installation flag, or a
Git repository address in this box.

Example package requirements, entered separately:

```text
pandas==2.2.1
numpy>=1.26,<2
scipy
matplotlib==3.8.4
```

After installing other packages, check that NumPy still satisfies `numpy>=1.26,<2`
when using pandas 2.2.1. If necessary, install that NumPy requirement again and
check that pandas imports before submitting a run.

If your package index provides a release of `labUtils`, enter its published
name and version in the same box. For example, `labUtils==0.4.0` applies only
if that release exists on your configured index. Otherwise follow section 3.3.

Examples of entries the package box rejects:

```text
-e /srv/labUtils
--index-url https://pypi.internal/
git+https://github.com/rpazuki/lab_utils.git
labUtils @ git+https://github.com/rpazuki/lab_utils.git#subdirectory=src
```

### 3.3. Install `labUtils` from a GitHub URL

Use this procedure when the library is supplied as a GitHub repository URL
instead of a package available through **Install a package**. For `labUtils`,
use `https://github.com/rpazuki/lab_utils.git`.

Complete the commands below in your server SSH session. They clone the source
and configure tasks to import it. Do not paste the GitHub URL into the browser's
package installation box. Skip this subsection if the required library is
already installed in the environment from a package index.

1. Create the parent directory:

   ```bash
   sudo install -d -o biopipeline -g biopipeline -m 0755 \
     /var/lib/biopipeline2/libraries
   ```

2. Clone the repository. Skip this command if it is already cloned:

   ```bash
   sudo -u biopipeline git clone https://github.com/rpazuki/lab_utils.git \
     /var/lib/biopipeline2/libraries/lab_utils
   ```

3. Confirm that the source directory contains the Python package:

   ```bash
   sudo -u biopipeline test -d \
     /var/lib/biopipeline2/libraries/lab_utils/src/labUtils
   ```

4. Record the selected source revision in your installation notes:

   ```bash
   sudo -u biopipeline git -C /var/lib/biopipeline2/libraries/lab_utils rev-parse HEAD
   ```

5. Open the deployment configuration:

   ```bash
   sudoedit /etc/biopipeline2/biopipeline2.env
   ```

6. Set the entry below. Preserve other library paths already in the list. Keep
   the outer single quotes so the systemd environment file preserves the JSON
   double quotes:

   ```text
   BP_TASK_LIBRARY_PATHS='["/var/lib/biopipeline2/libraries/lab_utils/src"]'
   ```

7. Save the file. After active tasks have finished, restart the worker services:

   ```bash
   sudo systemctl restart 'biopipeline2-worker@*'
   ```

8. Confirm that the worker services are active:

   ```bash
   systemctl --no-pager status 'biopipeline2-worker@*'
   ```

Keep this checkout unchanged while runs use it. Install its third-party
dependencies through 3.2; mounting source does not install dependencies.

For another library supplied through a GitHub URL, repeat this procedure with
its repository URL and a separate destination under
`/var/lib/biopipeline2/libraries`. In `BP_TASK_LIBRARY_PATHS`, add the directory
containing that library's importable Python package. For example, if the package
is at `/var/lib/biopipeline2/libraries/another_library/src/another_package`, add
`/var/lib/biopipeline2/libraries/another_library/src`. Preserve the existing
`labUtils` entry and restart the worker services after saving the configuration.

### 3.4. Check installed modules

1. Select the environment in **Environments**.
2. Under **What a pipeline can call**, enter an installed module such as
   `pandas` and inspect the returned functions.
3. Check source-mounted libraries with the test run in section 7. The module
   inspector reads the installed environment; it does not include the worker's
   additional source mounts.

## 4. Register shared storage, if needed

Skip this section if users will upload all input files and download all results
through the browser.

1. Choose an existing data directory on the worker server, outside
   `/var/lib/biopipeline2`.
2. Check that `biopipeline` can read the intended input files. For an output
   destination, also check that it can create files there.
3. Confirm that application users who will select this storage are authorised
   to access its contents.
4. Open **Storage → Register root** and complete these fields. Replace the
   example path with the directory you checked.

   | Field | Value to enter |
   | --- | --- |
   | `id` | A short identifier, for example `lab-share` |
   | `label` | A readable name, for example `Lab input files` |
   | `root_path` | The absolute server path, for example `/mnt/labshare/data` |
   | `attestation_note` | Who checked access, when, which users are authorised, and which service account accesses the directory |
   | `readable` | Enable for input storage |
   | `writable` | Enable only for an approved result destination |

5. Save the root and confirm it appears in the storage list.

Example values for an input-only share; replace the path, date and access
statement with values you have checked:

```json
{
  "id": "lab-share",
  "label": "Lab input files (read-only)",
  "root_path": "/mnt/labshare/data",
  "attestation_note": "Checked on YYYY-MM-DD by NAME: biopipeline can read this directory; all intended application users are authorised members of GROUP.",
  "readable": true,
  "writable": false
}
```

## 5. Create the pipeline

Use these two supplied files together:

| File | Purpose |
| --- | --- |
| [`examples/components/growth_rates.yaml`](../../examples/components/growth_rates.yaml) | Names reusable sequences of Python function calls |
| [`examples/pipelines/od600_growth_rates.yaml`](../../examples/pipelines/od600_growth_rates.yaml) | Selects those sequences and specifies inputs, parameters and output directories |

The example expects optical density measurements at a wavelength of 600
nanometres, named `od600` in the input table. Optical density measures how much
light a sample attenuates. The example calls functions that transform these
measurements and estimate growth rates over time. Use input files and function
signatures that match your installed `labUtils` version.

### 5.1. Create the component library

1. Display the example component source in your server session:

   ```bash
   cat /opt/biopipeline2/examples/components/growth_rates.yaml
   ```

2. Copy the complete file contents.
3. In the browser, open **Pipelines → Components → New component**.
4. Set **Library filename** to `growth_rates.yaml` and paste the contents into
   **Component document**.
5. Click **Validate component** and resolve any reported errors.
6. Click **Save component revision**.
7. Confirm that the component is listed. Use **View / edit** to read its source
   and **Saved component revisions** to load an earlier version.

To start a new pipeline using one graph, click **Use … in a pipeline** after
saving. The editor starts with that component reference; add the required stage
inputs and parameter overrides before running it. For the complete supplied
pipeline, continue with section 5.2 instead.

Alternatively, install the component file directly on the server:

1. Find `BP_COMPONENT_LIBRARY_ROOT` in
   `/etc/biopipeline2/biopipeline2.env`. The commands below use its default value,
   `/var/lib/biopipeline2/components`. Substitute the configured path if different.
2. Create the directory and copy the supplied component file:

   ```bash
   sudo install -d -o biopipeline -g biopipeline -m 0755 \
     /var/lib/biopipeline2/components
   sudo install -o biopipeline -g biopipeline -m 0644 \
     /opt/biopipeline2/examples/components/growth_rates.yaml \
     /var/lib/biopipeline2/components/growth_rates.yaml
   ```

3. Verify that the service account can read the file:

   ```bash
   sudo -u biopipeline test -r /var/lib/biopipeline2/components/growth_rates.yaml
   ```

### 5.2. Save a pipeline revision in the application

1. Display the supplied pipeline document:

   ```bash
   cat /opt/biopipeline2/examples/pipelines/od600_growth_rates.yaml
   ```

2. Copy the complete file contents.
3. In the browser, open **Pipelines → Pipelines → New revision**.
4. Enter a title such as `Growth-rate example`.
5. Paste the contents into **Pipeline document**.
6. Click **Compile**.
7. Resolve every error in the diagnostics and click **Compile** again after
   editing. Use the [pipeline format reference](../authoring/pipeline-format.md)
   to check field names and parameter syntax.
8. Confirm the preview includes the inputs `data_root` and `mapping_yaml`.
9. Click **Create revision**.
10. Confirm the pipeline page lists the saved revision. Record its version for
    section 6.

If you use your own pipeline, copy each component file named by its `components`
entries into the configured directory before compiling. A pipeline with inline
`steps` and no component imports does not need section 5.1.

To read or revise a saved pipeline, including one used by a published catalog
entry:

1. Open **Pipelines** and select the pipeline.
2. Find the required version in **Revisions** and click **View source** to read
   or copy its saved document.
3. Click **Create revision from this** to open that document in the editor.
4. Edit it, click **Compile**, resolve errors, and click **Create revision**.
5. Use section 6 to publish the new revision when ready. Saving alone does not
   change the catalog entry or previous runs.

### 5.3. Example: write steps directly in a pipeline

To practise with a shorter document, paste this example into **Pipeline
document** instead of the supplied full pipeline. Click **Compile**, then
**Create revision**. It calls only the parsing function; use the full example
from 5.2 for the subsequent growth-rate and publication examples.

```yaml
pipeline: parse_measurements
title: Parse measurement files
defaults:
  raw_data: $WILL_PROVIDE$
  meta_data: $WILL_PROVIDE$
  od600_col: od600
inputs:
  raw_data:
    accept: file
    sources: [shared, upload]
    help: Measurement table in the format required by labUtils.media_bot.parse.
  meta_data:
    accept: file
    sources: [shared, upload]
    help: Metadata table describing the samples in the measurement file.
stages:
  - name: parse
    steps:
      - name: df_parsed
        package: labUtils.media_bot
        method: parse
        parameters:
          raw_data: "{raw_data}"
          meta_data: "{meta_data}"
          value_column_name: "{od600_col}"
```

For this document, expose `raw_data` and `meta_data` as required file fields
when publishing. The parsed table is a Python return value; this example does
not declare downloadable output files. To create downloads, add a function
that writes results and declare the directory it writes under `outputs`.

### 5.4. Example: import a component and declare outputs

Read this extract alongside the full document in 5.2. The component name
`growth` connects `uses: growth` to a named graph in `growth_rates.yaml`.
The stage supplies the two files expected by that graph.

```yaml
components:
  growth:
    library: growth_rates.yaml
    graph: growth_rate_fit_pipeline
stages:
  - name: fit
    uses: growth
    inputs:
      raw_data: "{raw_data}"
      meta_data: "{meta_data}"
    step_parameters:
      df_fit_max_growth_rate:
        moving_window_size: 5
    outputs:
      results:
        path: processed/fit
        delivery: [download]
        retention_days: 90
```

This is an extract, not a complete pipeline document. Declare `raw_data` and
`meta_data` in `defaults` and `inputs` as in 5.3 before compiling it. Ensure a
called function writes files into `processed/fit`; the output declaration
specifies where to collect files and does not itself write them.

## 6. Add the pipeline to the catalog

1. Open **Publications → New publication**.
2. Select the pipeline and the revision saved in section 5.
3. Enter the catalog entry's title and description.
4. Under **Choose what to expose**, expose the inputs `data_root` and
   `mapping_yaml` for the supplied example.
5. Label `data_root` as `Input folder`; select the directory type and make it
   required.
6. Label `mapping_yaml` as `File mapping`; select the file type and make it
   required.
7. Expose additional parameters only if users should edit them when submitting
   a run. Give each exposed field a label and help text.
8. Check the form preview. Confirm both required input controls appear.
9. Click **Publish**.
10. Open **Catalog** and confirm the new entry is listed.

### 6.1. Example field bindings

A binding connects a form field to a pipeline input or parameter. For the full
pipeline from 5.2, use these examples when selecting which values to expose:

| Form field | Binding target | Pipeline location |
| --- | --- | --- |
| Input folder | `default_value` | `data_root` |
| File mapping | `default_value` | `mapping_yaml` |
| Moving window size | `step_parameter` | Stage `fit`, step `df_fit_max_growth_rate`, parameter `moving_window_size` |
| Measurement column | `step_parameter` | Stage `fit`, step `df_parsed`, parameter `value_column_name` |
| Raw measurement file | `stage_input` | Stage `fit`, input `raw_data` |
| Results directory | `stage_output` | Stage `fit`, output `results`; do not use this to configure delivery destinations |

Use `default_value` only for inputs declared with `$WILL_PROVIDE$`. For a value
already substituted during compilation, bind to the step parameter instead.
Use the stage name `fit`, including when the full example expands it into
multiple tasks.

### 6.2. Example field properties

Use these values when configuring publication fields through the application
programming interface (API). The browser editor exposes a subset of these
properties.

| Property | Example | Setting |
| --- | --- | --- |
| `key` | `data_root` | Submission field identifier |
| `label` | `Input folder` | Form label |
| `field_type` | `directory`, `file`, `string`, `integer`, `number`, `boolean`, `enum`, `url`, `object`, `array` | Input value type |
| `required` | `true` | Require a value |
| `help_text` | `Folder containing measurement and metadata files.` | Form instructions |
| `placeholder` | `/mnt/labshare/data/example` | Example shown in the control |
| `ui_group` | `Inputs` | Form section |
| `default_value` | `5` | Initial editable value |
| `fixed_value` | `od600` | Value applied without user editing |
| `visibility` | `visible`, `hidden`, `readonly` | Control visibility and editing |
| `type_ref` | `CustomReplicateRule` | Type defined in the selected pipeline document |
| `saveable` | `true` | Allow users to name and reuse the entered value |
| `source_policy` | `{"sources": ["shared", "upload"]}` | Allowed file sources |
| `delivery_policy` | `{"shared_root": "lab-share"}` | Delivery metadata; configure actual delivery in the pipeline and registered storage |

Put fields in the desired display order in the request's `fields` array.

### 6.3. Example: create and publish through the API

Use this procedure instead of the browser publication steps if you need the
properties in 6.2. Use the full pipeline revision created in 5.2.

1. In a Bash session with Python 3 and `curl`, set the application address and
   pipeline revision identifier. Replace both example values. Use the revision
   identifier returned when the pipeline was created, not its version number:

   ```bash
   BP_EXAMPLE_URL='https://your-server.example:8443'
   BP_EXAMPLE_REVISION='REPLACE_WITH_PIPELINE_REVISION_UUID'
   BP_EXAMPLE_PYTHON=python3
   ```

   On the deployment server, set `BP_EXAMPLE_PYTHON` to
   `/opt/biopipeline2/.venv/bin/python` if `python3` is unavailable.

2. Sign in as an administrator. Enter your email and password at the prompts.
   The password is hidden and is sent through standard input rather than a
   command-line argument. Keep the cookie file private:

   ```bash
   umask 077
   BP_EXAMPLE_COOKIE=$(mktemp)
   "$BP_EXAMPLE_PYTHON" -c 'import getpass,json,sys; sys.stderr.write("Administrator email: "); email=input(); print(json.dumps({"email":email,"password":getpass.getpass("Password: ")}))' \
     | curl --fail-with-body --silent --show-error \
         "$BP_EXAMPLE_URL/api/v1/auth/login" \
         -H 'Content-Type: application/json' \
         -H 'X-Requested-With: BioPipeline2' \
         -c "$BP_EXAMPLE_COOKIE" --data-binary @-
   ```

3. Save the following content as `publication.json`. Replace
   `REPLACE_WITH_PIPELINE_REVISION_UUID` with `BP_EXAMPLE_REVISION`'s value.
   Choose a different `slug` if this catalog entry already exists:

   ```json
   {
     "slug": "growth-rates-example",
     "pipeline_revision_id": "REPLACE_WITH_PIPELINE_REVISION_UUID",
     "title": "Growth-rate example",
     "description": "Process measurement files using the selected pipeline revision.",
     "fields": [
       {
         "key": "data_root",
         "label": "Input folder",
         "binding": {"target": "default_value", "binding_key": "data_root"},
         "field_type": "directory",
         "required": true,
         "help_text": "Folder containing measurement and metadata files.",
         "placeholder": "/mnt/labshare/data/example",
         "ui_group": "Inputs",
         "source_policy": {"sources": ["shared", "upload"]}
       },
       {
         "key": "mapping_yaml",
         "label": "File mapping",
         "binding": {"target": "default_value", "binding_key": "mapping_yaml"},
         "field_type": "file",
         "required": true,
         "ui_group": "Inputs",
         "source_policy": {"sources": ["shared", "upload"]}
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
         "default_value": 5,
         "ui_group": "Fitting",
         "help_text": "Number of consecutive measurement points per fitted window."
       },
       {
         "key": "od600_col",
         "label": "Measurement column",
         "binding": {
           "target": "step_parameter",
           "stage": "fit",
           "step": "df_parsed",
           "binding_key": "value_column_name"
         },
         "field_type": "string",
         "fixed_value": "od600",
         "visibility": "hidden"
       }
     ]
   }
   ```

4. Create the publication revision and save its response:

   ```bash
   curl --fail-with-body --silent --show-error \
     "$BP_EXAMPLE_URL/api/v1/publications/revisions" \
     -H 'Content-Type: application/json' \
     -H 'X-Requested-With: BioPipeline2' \
     -b "$BP_EXAMPLE_COOKIE" --data-binary @publication.json \
     -o publication-created.json
   cat publication-created.json
   ```

5. Extract the publication and publication-revision identifiers from that
   response. The publication revision differs from the pipeline revision:

   ```bash
   BP_EXAMPLE_PUBLICATION=$("$BP_EXAMPLE_PYTHON" -c 'import json; print(json.load(open("publication-created.json"))["publication_id"])')
   BP_EXAMPLE_PUBLICATION_REVISION=$("$BP_EXAMPLE_PYTHON" -c 'import json; print(json.load(open("publication-created.json"))["revision_id"])')
   ```

6. Publish the revision:

   ```bash
   curl --fail-with-body --silent --show-error -X POST \
     "$BP_EXAMPLE_URL/api/v1/publications/$BP_EXAMPLE_PUBLICATION/publish?revision_id=$BP_EXAMPLE_PUBLICATION_REVISION" \
     -H 'X-Requested-With: BioPipeline2' -b "$BP_EXAMPLE_COOKIE"
   ```

7. Confirm the entry appears in **Catalog**. Sign out of this command-line
   session and remove its cookie file:

   ```bash
   curl --fail-with-body --silent --show-error -X POST \
     "$BP_EXAMPLE_URL/api/v1/auth/logout" \
     -H 'X-Requested-With: BioPipeline2' -b "$BP_EXAMPLE_COOKIE"
   rm -- "$BP_EXAMPLE_COOKIE"
   ```

### 6.4. Example: define a reusable structured value

For a custom function accepting a structured parameter, add a type definition
to its pipeline document before compiling and saving a new revision:

```yaml
definitions:
  CustomReplicateRule:
    description: Settings for grouping repeated measurements of the same condition.
    fields:
      direction:
        type: enum
        required: true
        options: [alphabetical, numerical]
      sample_size:
        type: integer
        required: true
        default: 3
      labels:
        type: string
        container: list
```

To expose that value, add a publication field such as the following. First
replace the stage, step and parameter names with ones present in your pipeline
and accepted by your function. The full supplied example does not contain
`df_combined.custom_rules`; do not add this field to its request unchanged.

```json
{
  "key": "replicate_rule",
  "label": "Grouping rule",
  "binding": {
    "target": "step_parameter",
    "stage": "fit",
    "step": "df_combined",
    "binding_key": "custom_rules"
  },
  "field_type": "object",
  "type_ref": "CustomReplicateRule",
  "saveable": true,
  "ui_group": "Advanced"
}
```

## 7. Submit a test run

1. Prepare a small input folder in the format expected by the selected Python
   functions. For the supplied example, include measurement files and their
   corresponding metadata files, which describe the samples in those files.
2. Create a mapping file associating each measurement file with its metadata
   file. Names are relative to the input folder. For example:

   ```yaml
   measurements.csv: sample_metadata.csv
   ```

3. Open **Catalog** and select the entry from section 6.
4. For **Input folder**, upload the folder or select its registered shared-storage
   location.
5. For **File mapping**, upload the mapping file or select its registered
   shared-storage location.
6. Fill in other required fields and click **Submit**.
7. On the run page, wait for the tasks to finish.
8. Open each task's log. Resolve missing modules, incompatible function
   arguments, or input-format errors before repeating the run.
9. Confirm every task succeeded.
10. Download the expected output files and inspect their contents. For a pipeline
    you authored, ensure its Python functions write files under the output paths
    declared in its pipeline document.

### 7.1. Example: run an unpublished revision as an administrator

1. Open **Pipelines** and select the saved revision.
2. Click **Run**.
3. Supply its required inputs and submit.
4. Check the task logs and output files as in section 7.

### 7.2. Example: schedule repeated runs

1. Open **Schedules → New schedule**.
2. Select the published catalog entry.
3. Fill in its input form.
4. Set the repetition interval, first execution time and end condition.
5. Save the schedule and confirm the next execution time shown on its page.

## 8. Check service health

1. Open **Administration → Fleet → Right now**.
2. Confirm a worker is reporting activity and that the test run has no tasks left
   waiting.
3. Check for stopped deliveries and low free disk space.
4. Use [monitoring.md](monitoring.md) for ongoing checks and
   [backup-and-restore.md](backup-and-restore.md) to configure backups.

To run a manual storage reconciliation check, execute:

```bash
sudo -u biopipeline /opt/biopipeline2/.venv/bin/python \
  /opt/biopipeline2/scripts/ops/reconcile.py
```

## Resolve setup errors

| Error | Action |
| --- | --- |
| Permission denied while cloning `labUtils` | Create the parent directory with the ownership shown in 3.3, then retry. |
| Package installation failed | Open **Environments → History** and read the failed operation's log. Correct its reported cause before retrying. |
| Environment remains busy after an interrupted request | Check the server log and running containers. Use **Clear the lock** only after confirming the build is no longer running. |
| `ModuleNotFoundError` | Check the package installation or source path in section 3, dependencies, and worker restart. |
| Component file not found | Check `BP_COMPONENT_LIBRARY_ROOT`, the imported filename and the read-permission check in 5.1. |
| Task remains queued | Check the worker service and resource limits in [deployment.md](deployment.md). |
| Permission denied writing `/work` or `/env` | Follow the ownership checks in [deployment.md](deployment.md#when-it-does-not-work). |
| Input is outside registered storage | Register its parent directory using section 4, or upload the input. |
