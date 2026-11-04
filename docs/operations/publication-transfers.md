# Publish folder inputs and downloadable results

## 1. Save a demonstration pipeline

1. Sign in as an administrator.
2. Open **Pipelines → Pipelines → New pipeline**.
3. Paste the following YAML:

```yaml
pipeline: directory_copy_demo
title: Directory copy demonstration
defaults:
  data: $WILL_PROVIDE$
inputs:
  data:
    accept: directory
stages:
  - name: copy
    steps:
      - name: copied
        package: shutil
        method: copytree
        parameters:
          src: "{data}"
          dst: outputs/copied
          dirs_exist_ok: true
    outputs:
      results:
        path: outputs/copied
```

4. Compile and save the revision.

The example copies the input directory into a results directory. `shutil` is
part of Python's standard library; no additional package installation is
required. `dirs_exist_ok` allows copying into the output directory prepared by
the task runner.

## 2. Select input methods and result downloads

1. Open **Publications → New entry**.
2. Select the demonstration pipeline and its saved revision.
3. Enter a title such as `Copy an uploaded directory`.
4. Keep `data` included and select **Ask the researcher**.
5. Under **Allowed input methods**, select the methods to offer:
   - **Upload a folder:** send files from a directory on the researcher's computer.
   - **Upload a ZIP archive:** expand a ZIP file into an input directory.
   - **Registered shared storage:** use a directory within an attested, readable storage root.
6. Under **Result downloads**, select individual files, a ZIP file, or both.
7. Check the preview and click **Publish**.

Keep individual downloads enabled when results may exceed the configured ZIP
limit. The default ZIP limit is 20 gibibytes, or $20 \times 1024^3$ bytes, and
20,000 members. An operator can adjust the limits in section 6.

## 3. Submit a local folder

1. Open the entry in **Catalog**.
2. Select **Upload a folder**.
3. Click **Choose folder** and select a directory containing test files.
4. Wait for the upload and directory checks to finish.
5. Submit the run.
6. Open the run and wait for completion.

The selected directory's contents become the input root. For example,
`experiment/raw/input.csv` becomes `raw/input.csv` within the staged input.
Nested file paths are preserved. Browser folder selection does not report
empty subdirectories; use ZIP input when those must be retained.

If a transfer fails, select the same files again to resume completed or partial
transfers within the open form. Refreshing or closing the form loses its local
resume state. Submitted runs retain their uploaded inputs independently of the
form.

## 4. Submit a ZIP file

1. Create a ZIP containing the desired directory contents.
2. Open the catalog entry and select **Upload a ZIP archive**.
3. Choose the ZIP and wait for checking and extraction.
4. Submit the run after the directory is ready.

The ZIP's internal root is preserved. A ZIP containing `raw/input.csv` supplies
`raw/input.csv`; a ZIP containing `experiment/raw/input.csv` retains the
`experiment` directory. Empty files and explicitly stored empty directories are
preserved. Archives with unsafe paths, links, duplicate destinations, encrypted
members, unsupported compression, or excessive expanded size are rejected.
The ZIP's directory metadata, containing member names and archive attributes,
must fit within 16 mebibytes.

## 5. Retrieve results

1. Open the completed run.
2. Under **Outputs**, use individual download links or expand a directory's
   **Files** list if that method was enabled.
3. For a complete archive, click **Prepare results ZIP**.
4. Wait for the delivery service to finish preparation.
5. Click **Download results ZIP**.

The archive includes the run's available output artifacts and preserves nested
paths and empty directories. Separate artifact prefixes prevent identically
named outputs from replacing one another. Logs and uploaded inputs are not
included in the results bundle.

Repeated requests reuse the prepared ZIP while it remains available. A failed
request can be retried. If retention removes the prepared archive, prepare it
again while the original outputs remain available.

Publication choices are frozen when a run is submitted. Existing runs created
before these settings retain individual downloads. Publish a new revision and
submit a new run to use the new publication choices.

## 6. Configure limits and the delivery service

1. Set limits in `/etc/biopipeline2/biopipeline2.env` if the defaults need changing:

```bash
BP_UPLOAD_DIRECTORY_MAX_BYTES=21474836480
BP_UPLOAD_DIRECTORY_MAX_FILES=20000
BP_OUTPUT_BUNDLE_MAX_BYTES=21474836480
BP_OUTPUT_BUNDLE_MAX_FILES=20000
```

2. Restart the API and courier after changing these settings:

```bash
sudo systemctl restart biopipeline2-api biopipeline2-courier
sudo systemctl status biopipeline2-courier --no-pager
```

3. If ZIP preparation remains queued, inspect the delivery service:

```bash
sudo journalctl -u biopipeline2-courier -n 100 --no-pager
```

4. For inputs too large for browser transfer, register readable shared storage
   and enable that input method in the publication.
