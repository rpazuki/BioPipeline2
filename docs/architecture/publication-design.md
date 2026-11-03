# Publication design and implementation plan

## Responsibilities

1. A **component** defines reusable computation: Python calls and their connections.
2. A **pipeline revision** assembles components and declares the values, files, and directories required for execution. It does not choose browser controls or archive formats.
3. The **publication library** is maintained by administrators. It contains named data types and named values, including scalar constants, structured objects, and enumerations whose choices may return entire objects.
4. A **publication revision** selects a pipeline revision and chooses the form: labels, groups, required fields, editable defaults, fixed values, reusable types, input transfer methods, and output delivery methods.
5. A **submission** supplies the editable values. The platform validates them, transfers files, and passes ordinary values and local paths to the computation.

For example, a pipeline asks for a window size. The library contains `standard_window` with integer value `5`. One publication fixes that value; another offers `5` as an editable default. Neither choice requires recompiling the pipeline.

## Comparison with the old project

The old project's project-level type library and publication-time type selection are useful responsibilities to retain. Its named reusable values and object-valued choices must also remain possible. Researcher-owned saved values are a separate feature: they belong to a person, whereas administrator presets are shared authoring resources.

The current backend already stores fixed values, defaults, and resolved type snapshots. However, its publication editor offers only an exposure checkbox and primitive type selection. Custom schemas currently come from pipeline source. Folder transfer and ZIP output delivery are also missing from the new interface.

The existing `type_definitions` table has no authoring routes or consumers. This implementation introduces one project-level publication-library document for atomic validation of references between types and presets. Existing pipeline-local definitions and researcher saved values remain compatible. Consolidating the unused table is a later schema cleanup, not a prerequisite for this change.

## Publication contract

Each bindable target has one of three modes:

- **Use pipeline value:** no publication override. Only valid when the pipeline already supplies the value.
- **Ask the researcher:** show a control, optionally initialized from a literal value or a library preset.
- **Fixed value:** store a literal value or library preset in the publication and hide the control. Submitted attempts to replace it are rejected.

A named type is selected independently of the Python call. Its resolved schema is copied into the publication. A library preset supplies a type and value; its value is copied into the publication as a default or constant. The editor submits the library digest it previewed. A changed library requires refreshing before publication, so preview and stored values cannot silently disagree.

Publication validation checks bindings, required-input coverage, type references, and default/fixed values before writing a revision. A published pipeline's own declared schema remains an execution requirement: a publication type must not replace it with an incompatible schema. The initial implementation requires an identical resolved schema when both are present.

Library updates use an optimistic concurrency digest and a database lock. Published revisions never consult the mutable library during submission or execution. If the library is edited or a preset is removed, existing publications continue to use their frozen schemas and values.

## Input and output transport

Publication choices should ultimately include:

| Execution requirement | Publication choices | Value passed to computation |
| --- | --- | --- |
| Scalar or structured value | Typed control, editable preset, fixed preset | Validated value |
| File | Browser upload or registered shared storage | Local file path |
| Directory | Browser folder, ZIP upload, or registered shared storage | Local directory path |
| Output file | Individual download or inclusion in a ZIP bundle | Existing artifact |
| Output directory | Browse members or download a ZIP bundle | Existing directory artifact |

Transfer adapters must stage files before execution. Archive extraction must reject absolute paths, parent traversal, symbolic links, duplicate destinations, excessive file counts, and excessive expanded size. Downloads must respect existing run ownership and artifact access checks. Archive generation must be bounded and must not load an entire result into application memory.

Pipeline `sources` declarations currently constrain materialisation. Moving transport selection completely to publications requires changing that execution path as well as the form. Merely adding folder or ZIP controls would create a form that cannot execute reliably.

## Implementation sequence

### 1. Publication authoring foundation — implement now

- Add an administrator-only, project-level YAML library editor with reusable type definitions and named presets.
- Validate all type references and preset values before saving; reject concurrent overwrites.
- Add explicit researcher/fixed modes, literal defaults/constants, type selection, and preset selection to the publication editor.
- Resolve selected presets on the server and freeze values and schemas in the publication revision.
- Use the resolved schema in the same form component used by the catalog preview.
- Preserve existing pipeline-local schemas and researcher saved values.
- Test authorization, stale edits, invalid values, object-valued enumerations, fixed-value override rejection, and publication stability after library changes.

### 2. Publication-controlled transfers

- Make supported file and directory sources explicit publication settings and enforce them on submission.
- Implement folder and ZIP staging with the limits and path checks above.
- Preserve existing direct administrative pipeline submission as a separate execution workflow.
- Test upload ownership, source restrictions, extraction failures, and successful execution with staged directories.

### 3. Result delivery

- Add publication-controlled individual and ZIP download choices.
- Generate bundles from immutable artifacts with access checks, bounded processing, clear progress, and cleanup.
- Test nested directories, empty results, repeated downloads, and access by another user.

### 4. Migration and deployment

- Document executable examples for defining types/presets and selecting them during publication.
- Provide an explicit import path for old type libraries and named values; do not silently import old input preprocessing or output serializers.
- Run database-backed regression tests, frontend checks, contract generation, and a production frontend build before deployment.

Each implementation stage is independently useful. Stage 1 does not claim to provide folder uploads or ZIP downloads; those require stages 2 and 3.
