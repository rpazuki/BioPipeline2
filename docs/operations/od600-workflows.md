# Install the optical-density growth-rate workflows

## 1. Update the application

1. Deploy the application commit containing `scripts/operations/import_od600.py`.
2. Apply database migrations with `alembic upgrade head` from the backend directory.
3. Rebuild the configured task image from `deploy/images/task/Dockerfile`.
4. Confirm that the default execution environment has a ready generation.
5. Confirm that `BP_TASK_LIBRARY_PATHS` includes the installed `lab_utils/src` directory.

## 2. Check the definitions

1. Run the command below as the application service account, with the same environment variables as the application.
2. Replace `administrator@example.org` with an existing active administrator's email address.
3. Check that the report lists two publications. The command rolls back its database changes and writes no component files.

```bash
/opt/biopipeline2/.venv/bin/python /opt/biopipeline2/scripts/operations/import_od600.py --admin-email administrator@example.org --check
```

## 3. Install the definitions and required packages

1. Back up the database, component directory, and application configuration.
2. Stop application writers and workers for the import.
3. Run the following command as the application service account with its configured environment variables.

```bash
/opt/biopipeline2/.venv/bin/python /opt/biopipeline2/scripts/operations/import_od600.py --admin-email administrator@example.org --prepare-environment --replace-existing
```

4. Confirm that runtime imports pass and that the report lists `od600-growth-rates-single` and `od600-growth-rates-multiple`.
5. Restart the application services and workers.

The package preparation uses new environment generations. The replacement option withdraws other catalog entries, archives other pipelines, and removes other current component files while retaining their source snapshots. Saved revisions and run records remain available. Omit `--replace-existing` to keep other definitions active. Repeating the same import reuses its pipeline and publication revisions.

## 4. Submit a single experiment

1. Open **Catalog → OD600 growth rates — single experiment**.
2. Select an averaging method: fit each well, average measurements before fitting, or average fitted growth rates.
3. Review the well grouping rules and fitting controls.
4. Keep the sample name pattern as `(\w+)` to capture the complete sample name, or enter another regular expression containing a capture group.
5. Upload the measurement file and its sample metadata file separately.
6. Submit the run and open it from **Runs**.
7. When it succeeds, browse the result files or download the ZIP archive.

## 5. Submit several experiments

1. Open **Catalog → OD600 growth rates — multiple experiments**.
2. Select an averaging method and review the fitting controls.
3. Upload the folder containing the measurement and metadata files, or upload a ZIP archive containing that folder's contents.
4. Create and upload a mapping file such as:

```yaml
measurements_1.csv: metadata_1.csv
measurements_2.csv: metadata_2.csv
```

5. Use filenames relative to the uploaded folder. Include nested directory names when needed.
6. Submit the run. The selected method creates one task for each mapping entry.
7. Download the results after the run succeeds. Each experiment has its own output subdirectory.

## 6. Remove definitions through the interface

1. Open **Publications** and use **Withdraw** to remove an entry from the catalog.
2. Open **Pipelines → Pipelines** and use **Archive** to remove a pipeline from the active authoring list.
3. Open **Pipelines → Components** and use **Remove** to remove a current component library.
4. Confirm the relevant dialog. Resolve any reported concurrent-change error before retrying.
