# Optical-density growth-rate migration

## Sources and scope

The reviewed bundle is in [`examples/migrations/od600`](../../examples/migrations/od600). It converts these files from the earlier project's `.bio_pipeline` directory:

- `yamls/growth_rates_pipeline.yaml`: three reusable processing graphs.
- `job_defs/OD600_growth_rates_ingestion.yaml`: a single-experiment workflow.
- `job_defs/Multiple_OD600_growth_rates_ingestion.yaml`: a workflow over measurement/metadata pairs from a mapping file.
- `type_library.yaml`: the `CustomReplicateRule` and `Strain_Pattern` definitions used by the publications.

The corresponding publication records in `state.sqlite` provide the researcher-facing controls, upload choices, and output download requirements. Source file hashes are recorded in `bundle.yaml`. The bundle uses native component, pipeline, type, preset, and publication definitions.

## Measurements and calculations

Optical density at a wavelength of 600 nanometres measures how much a sample attenuates light at that wavelength. The input is a series of readings for each well of a plate. Sample metadata associates each well with a sample name and other experimental information.

The existing `labUtils` functions transform a reading $x(t)$ to $y(t) = \log(x(t)/x_0)$, where $x_0$ is estimated from the initial observations. They fit a modified Gompertz curve and estimate a maximum slope using moving windows. When time is measured in hours, the corresponding slope has units of inverse hours. These computations remain in `labUtils`.

The fitted curve has the form $y(t) = y_0 + A \exp(-\exp((\mu e/A)(\lambda-t)+1))$. Here $A$ is the asymptotic increase in the logarithmic reading, $\mu$ is the fitted maximum slope, and $\lambda$ controls the horizontal lag. The migrated configuration fixes $y_0 = 0$ as in the original component.

Replicate wells are wells assigned to the same sample or experimental condition by the grouping rules.

The three variants retain distinct meanings:

1. **No averaging:** transform and fit each well separately.
2. **Average before fitting:** group replicate wells, average their measurements at each time, then fit the resulting series.
3. **Average after fitting:** fit wells separately, then aggregate the fitted growth-rate estimates according to the grouping rules.

`selects_variant: true` on the method input selects one of the already compiled, named matrix variants. It does not modify source YAML or choose an uncompiled Python function. Other matrix workflows retain their existing behavior of running every row.

## Explicit migration corrections

- Input preparation is represented by explicit path conversion and parser calls. Copying only the earlier `Processes` blocks would pass filenames where parsed tables are required.
- The original output mappings become explicit table-writing calls, with files stored inside each task's declared output directory. Multiple experiments retain distinct output paths.
- Unquoted template mappings and the nonuniform `group_cols_2` matrix attribute are removed. The graph already determines the correct grouping columns.
- The type-name string `CustomReplicateRule` is replaced by the original component's concrete named grouping rules, stored as an administrator preset with map shape.
- The sample name pattern defaults to `(\w+)`. A capture group is required by the installed implementation's use of `pandas.Series.str.extract`; the earlier `\w+` default fails that requirement.
- Post-fit aggregation keeps the component's `mu_max` and `mv_mu_max` measurement columns. Applying the job's general `od600` override to fitted-rate tables would refer to a missing column.
- The reviewed runtime requirements pin a compatible set of NumPy, pandas, Matplotlib, SciPy, contourpy, PyYAML, addict, and openpyxl versions. The inspected server generation had SciPy 1.18.1 and contourpy 1.4.0 alongside NumPy 1.26.4, which violates their NumPy requirements. SciPy 1.14.1 and contourpy 1.3.1 accept that NumPy version. Package preparation builds new generations and retains existing run pins.

## Verification

`backend/tests/science/test_od600_parity.py` runs each method in both single- and multiple-experiment form using synthetic measurements. It compares all declared tables and plot files with direct calls from the original component definition. The reference corrects the missing capture group in the original pattern before making those calls. Synthetic input files and the original component fixture are retained under `backend/tests/fixtures/od600`.

The check requires a configured scientific environment and installed `labUtils` source:

```bash
BP_TEST_OD600_GENERATION=/path/to/ready/generation BP_TEST_OD600_LIBRARY=/path/to/lab_utils/src BP_TEST_OD600_IMAGE=biopipeline2/task-base:1.0 .venv/bin/python -m pytest backend/tests/science -m slow -q
```

API tests cover import repetition, dry-run rollback, restoration of component sources after transaction failure, private saved-value types, removal permissions, and preserved revision access. Deployment instructions are in [`docs/operations/od600-workflows.md`](../operations/od600-workflows.md).
