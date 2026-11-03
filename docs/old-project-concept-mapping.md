# Concepts in bioPipeline and BioPipeline2

This comparison is based on the old project at
`C:\Users\rh2310\projects\bioPipeline` and the BioPipeline2 source.

An old **Pipeline** corresponds roughly to a BioPipeline2 **component graph**.
An old **Job Definition** corresponds roughly to a BioPipeline2 **pipeline
document**. The correspondence describes their roles; it does not mean that
renaming an old file converts it to the new format.

## Concept mapping

| Old bioPipeline concept | BioPipeline2 equivalent | Purpose |
| --- | --- | --- |
| Pipeline | Component graph | A reusable sequence of Python function calls |
| Job Definition | Pipeline document | Selects processing sequences, supplies inputs and parameter overrides, and specifies stages, dependencies and repetitions |
| Published Job | Publication / catalog entry | Presents a configured workflow as a form researchers can submit |
| Submitted Job Definition | Run | One submission with concrete input values, potentially producing multiple tasks |
| Individual queued job/task | Task within a run | One executable unit with its own status and log |

The word **job** in the old project has more than one meaning. A Job Definition
is a reusable workflow description; an individual queued job is an execution
record. Use the corresponding row above according to which meaning is intended.

## Example from the old project

The old file
`Jobs_Pipelines_backup/Pipeline_yamls/growth_rates_pipeline.yaml` contains a
named pipeline called `growth_rate_fit_pipeline`. It has three sections:

- `Inputs`: input sources and functions that prepare the input values.
- `Processes`: the Python function calls and their parameters.
- `Outputs`: mappings from returned values to output filenames.

The old Job Definition in
`Jobs_Pipelines_backup/job_defs/OD600_growth_rates_ingestion.yaml` selects a
named pipeline from that file:

```yaml
job: OD600_growth_rates_ingestion

variables:
  variant:
    - name: no_replicates
      pipeline: growth_rate_fit_pipeline
    - name: replicates
      pipeline: growth_rate_replicates_fit_pipeline

stages:
  - name: growth_rate_fit_pipeline
    pipeline_yaml: growth_rates_pipeline.yaml
    pipeline: "{variant.pipeline}"
```

This extract illustrates selection of a reusable pipeline for each variant.
It omits the old Job Definition's defaults, input sources, parameter overrides
and output directory; it is not a complete runnable Job Definition.

The example's measurements are optical density readings at a wavelength of
600 nanometres, identified by the column name `od600`. Optical density measures
how much a sample attenuates light. The processing functions use measurements
over time to estimate growth rates. Metadata files describe the samples
associated with those measurements.

## Corresponding structure in BioPipeline2

BioPipeline2's example component library is
[`examples/components/growth_rates.yaml`](../examples/components/growth_rates.yaml).
Its pipeline document is
[`examples/pipelines/od600_growth_rates.yaml`](../examples/pipelines/od600_growth_rates.yaml).

The corresponding selection structure is:

```yaml
pipeline: od600_growth_rates

components:
  growth:
    library: growth_rates.yaml
    graph: "{variant.graph}"

variables:
  variant:
    - name: no_replicates
      graph: growth_rate_fit_pipeline
    - name: replicates
      graph: growth_rate_replicates_fit_pipeline

stages:
  - name: fit
    uses: growth
```

This is a structural extract. Use the complete linked pipeline document for
its input declarations, file mapping, parameter overrides and output paths.

`growth` is a local alias within the pipeline document. `library` identifies
the component file, and `graph` selects a named sequence inside that file.
`uses: growth` inserts the selected sequence into the stage called `fit`.

| Old Job Definition field | Corresponding BioPipeline2 field |
| --- | --- |
| `job` | Top-level `pipeline` |
| Stage `pipeline_yaml` | Component `library` |
| Stage `pipeline` | Component `graph`, selected through stage `uses` |
| `variables` | `variables` |
| `defaults` | `defaults`, with explicit public `inputs` declarations where needed |
| Stage `input_sources` | Stage `inputs`, subject to the new input and storage rules |
| Stage `process_arg_mapping` | Stage `step_parameters` |
| Stage `output_dir` | Requires explicit migration of file writing and output declarations; there is no direct field replacement |

## Input and output behaviour must be migrated explicitly

The new component loader reads an old-style `Processes` block into step
definitions. It does not automatically translate the old pipeline's `Inputs`
and `Outputs` behaviour.

For example, the old component's `Inputs` section calls
`labUtils.media_bot.parse_raw_CLARIOstar_export` and
`labUtils.media_bot.parse_protocol_metadata`. Its `Outputs` section assigns
filenames such as `parsed_data.csv` and `growth_rates.csv` to returned values.
Copying only its process calls does not preserve those preparation and saving
operations.

For each migrated workflow:

1. Identify the old input preparation functions and the values they return.
2. Represent any required preparation as explicit calls compatible with the new
   pipeline and its installed Python library.
3. Preserve the required processing steps, arguments and data flow.
4. Add explicit result-writing calls where the old engine saved returned values.
5. Declare the resulting files or directories under the new stage's `outputs`.
6. Run the old and new workflows on the same test inputs and compare the files
   and results.

Successful compilation checks the pipeline structure. It does not by itself
demonstrate that input preparation, scientific calculations or result saving
match the old workflow.

## Source references

Old project, relative to `C:\Users\rh2310\projects\bioPipeline`:

- `docs/JOBS.md`: Job Definition, stage and task hierarchy.
- `src/bio_pipeline_manager/job_definition.py`: parsing and task expansion.
- `src/bio_pipeline_manager/models.py`: queued job specifications and records.
- `Jobs_Pipelines_backup/Pipeline_yamls/growth_rates_pipeline.yaml`: reusable processing sequences.
- `Jobs_Pipelines_backup/job_defs/OD600_growth_rates_ingestion.yaml`: workflow selecting those sequences.

BioPipeline2:

- [`backend/app/infrastructure/pipeline_loader.py`](../backend/app/infrastructure/pipeline_loader.py): loading component graphs.
- [`examples/components/growth_rates.yaml`](../examples/components/growth_rates.yaml): component example.
- [`examples/pipelines/od600_growth_rates.yaml`](../examples/pipelines/od600_growth_rates.yaml): pipeline example.
- [`docs/authoring/pipeline-format.md`](authoring/pipeline-format.md): pipeline format reference.
