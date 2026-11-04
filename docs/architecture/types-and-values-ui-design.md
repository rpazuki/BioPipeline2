# Types, presets, and personal saved values: interface design

## Scope and decision

This is a proposed design, based on the existing BioPipeline2 implementation and a review of the earlier BioPipeline project. It is not an installation guide or a record of deployed features.

Make visual editing the normal way to define types and values. Keep YAML as an equally capable advanced editor, with both views editing the same draft. Restore the earlier project's recursive value controls and personal saved-value management. Keep BioPipeline2's separation between computation, publication, and personal values, and its immutable publication revisions.

Legacy formats belong in administrator migration tools. They are not a prerequisite for creating types, presets, publications, or personal saved values.

## What the current import options mean

| Current label | Actual purpose | Proposed location and wording |
| --- | --- | --- |
| Old project type library | Convert type definitions exported from the earlier BioPipeline project into this project's library document. | Administration → Data transfer → Import from earlier BioPipeline → Type definitions |
| Old job defaults and named variants | Convert reusable values from earlier job definitions into administrator presets. This is not an import of complete jobs, publications, or personal saved values. | Administration → Data transfer → Import from earlier BioPipeline → Shared defaults and choices |
| Named presets with type references | Import a batch of shared values that identify their types. This is useful independently of the earlier project. | Types and presets → More → Import presets |

The earlier project used **job** for a published runnable configuration. Its **variants** were named alternative values. These historical terms should appear only inside the migration workflow, with an explanation beside the relevant input.

An administrator transferring an earlier deployment needs the source file, an import preview, warnings about unsupported semantics, and a conflict-resolution choice. Ordinary administrators and researchers need no knowledge of that format. Import remains optional, explicit, and reviewed before saving; it must never silently alter published entries.

## Findings from the earlier project

| Capability | Evidence in the earlier project | Gap or decision for BioPipeline2 |
| --- | --- | --- |
| Visual type creation | `TypeLibraryPanel.tsx` has simple and compound types, descriptions, field rows, primitive or named field types, required fields, defaults, enumerations, and single/list/map selection. | Replace whole-document YAML as the only authoring interface. |
| Recursive value editing | `TypedValueEditor.tsx` renders nested objects, lists, and named maps; primitive collections also have controls. | The present `TypedField.tsx` falls back to a text area for nested objects and collections. Implement recursive controls. |
| Rich published fields | `PublishedField` includes labels, help, examples, placeholders, required, read-only, nullable, saveable, defaults, single and multiple choices, and input/output settings. | Restore these responsibilities in the publication editor, rather than placing every setting on a type. |
| Field documentation | `TypeFieldSpec` supports help and examples. | Preserve and expose this metadata. The earlier visual type editor did not expose every supported metadata field. |
| Personal saved cases | A dedicated Saved Values page and `SavedCasesControl.tsx` support named cases, rename, delete, and a personal default. | The current inline save/use controls do not provide comparable management or default selection. |
| Reuse across publications | Saved values for named types are grouped by type and container; plain fields can be scoped to a particular published field. | Support both shared type identity and field-local values, with compatibility validation. |
| Class extraction | The type panel previews definitions extracted from a Python class before adding them to the library. | Retain explicit inspection as an optional administrator tool using a selected environment. |
| Published-form updates | The earlier type-library routes call `refresh_typed_field_schemas` after edits and deletion. | Do not copy this behavior. Existing BioPipeline2 publication revisions must retain their stored schemas and values. |

The earlier implementation is a reference for workflows, not code to copy without review. For example, duplicate map keys could overwrite a previous value, and some type-editor defaults were converted through strings. The replacement must block duplicate keys and preserve the actual types of values.

Range limits, regular expressions, and collection-size constraints are proposed extensions below. They were not established as working capabilities of the earlier visual editor during this review.

## Concepts users should see

1. **Type:** describes the permitted structure and values. For example, `ProcessingOptions` contains a required integer `window` and a Boolean `enabled`.
2. **Shared preset:** an administrator-owned named value of a type, such as `Standard options`, containing `window = 5` and `enabled = true`.
3. **Publication field:** chooses which type to use, whether to ask the researcher or fix the value, the initial value, and the presentation and transfer settings.
4. **Personal saved value:** a researcher's named configuration, reusable where it passes validation. It is private to its owner.

A preset is not inherently a constant: publication can use the same preset as either an editable default or a fixed hidden value.

### Value shape and saved cases are different

For a type $T$, let $V(T)$ be its permitted values. A single value is $x \in V(T)$. A list of length $n$ belongs to $V(T)^n$. A named map is a function $m: K \to V(T)$ for a finite set $K$ of string keys.

These are three shapes of **one complete value**. Several saved cases are several separately named complete values. For example, `Short windows` and `Long windows` may each hold an entire map of processing options. The interface must not use one ambiguous “multiple” checkbox for both concepts.

Choose **Single**, **List**, or **Named map** at a field binding or value editor. Named cases are available when the publication permits personal saving. Do not reproduce the earlier type-level `multiple` flag as an unexplained global restriction.

## Navigation and screens

### Administrator: Types and presets

Keep the existing publication-library destination, with two tabs: **Types** and **Shared presets**. Use the established Tabler styling throughout.

The selected arrangement is a focused editor: use a searchable list to choose an entry, then give the selected editor the available width. Keep navigation back to the list visible. Stack controls on narrow screens; changing the layout must not change the data model.

The type editor provides:

- A stable identifier, display name, and description. Display-name changes must not change saved-value identity.
- A choice between a simple value and an object with fields. A simple value may also be a labelled choice.
- Editable field rows showing key, label, type, shape, and required state. Expand a row for defaults, help, examples, and other details.
- Primitive types and references to other library types in the same selector. Show reference errors and cycles before saving.
- Add, remove, and move field actions. Warn about referenced fields and show affected presets and publications before a breaking change is saved.
- **Visual** and **YAML** modes for the same draft, plus **Preview** and **Used by** views. Preview has a Single/List/Named map selector independent of the type definition.
- A typed default editor with an explicit **No default / Supply a default** choice. `false`, `0`, an empty string, an empty collection, and `null` must not be mistaken for an absent default.
- A live form preview using the same value editor as published forms.

The advanced field panel distinguishes three independent questions: must the key be present, may its value be null, and does it have a default? A field that requires a present value must not become optional merely because its editor currently looks empty.

Use typed label/value rows for choices. A label can return a string, number, Boolean, or a complete structured value. Do not encode choice definitions in comma-separated strings. For structured choices, select a value type so that the option's value has a visual editor and server validation.

Support both one choice and several choices. Several choices produce a list of selected option values, preserving their actual types. Built-in lists and maps must also be available directly, without requiring an administrator to create an otherwise unnecessary named type.

Offer long text and date/time presentation where appropriate. A file or directory is a transfer requirement with publication-controlled sources, not merely a string that looks like a path. A textual path pattern remains a text value; it must not accidentally open a file-upload control.

After core parity, add server-enforced numeric bounds, text patterns, and collection-size limits. Expose a constraint only when the server also enforces it. There must be no decorative validation controls that apply only in the browser.

**Shared presets** use the same list/editor arrangement. Choose a type and shape, enter a value with the recursive value editor, and save it with a name and description. Show incompatible presets with an explanation when choosing one during publication. Referenced presets are archived or removed from future selection without altering frozen publications.

Place native import/export under **More**. Place earlier-project conversion under **Administration → Data transfer**, outside the normal editor.

### Administrator: Publication editor

For each input, show:

1. **Value supplied by:** pipeline value, researcher, or fixed value.
2. **Type and shape:** reusable type or built-in type, then Single/List/Named map.
3. **Initial or fixed value:** no initial value, enter a value, or use a shared preset. Entered values use the same recursive editor as presets.
4. **Presentation:** label, help, example, placeholder, group, order, and appropriate control hints.
5. **Personal saving:** whether this field may be saved, and whether a compatible personal default may initialize it.
6. **Transfers:** allowed input sources or result delivery, only for file and directory requirements.

Keep read-only visible values separate from hidden fixed values. Neither can be overridden by a submitted request. Pipeline types and execution requirements remain binding even if a publication changes presentation.

The publication preview and actual researcher form use the same renderer and frozen schema. Add a clearly labelled **Preview as researcher** action. Show a summary before publishing when a library change requires a new publication revision.

### Researcher: My saved values

Add **My saved values** to the navigation for researchers and administrators. An administrator sees their own personal values here, not everyone else's private configurations.

Group values by reusable type and shape, or by publication-field identity for plain fields without a reusable type. Within a group, list named cases and mark the personal default. Provide create, edit, duplicate, rename, delete, and **Set as my default** actions. Duplication and list reordering are improvements beyond the earlier controls verified in this review.

Use the recursive value editor, with a YAML option for structured values. Show the schema snapshot under which a case was saved and whether it is usable in the current context. An incompatible case remains readable and editable against its saved schema; offer an explicit copy-and-adapt operation rather than changing it silently.

In a published form, offer **Use saved value** and **Save these values** beside saveable inputs. A saved-value picker shows names and defaults, plus compatibility explanations. Loading a case replaces that complete field value only after the user chooses it. Private values become shared administrator presets only through a separate, explicit owner-authorized operation; importing a type library does not expose them.

### Initial-value precedence

For a newly opened editable form, initialize each field once from the first applicable source:

1. An explicitly loaded submission, draft, replay, or saved case.
2. A compatible personal default, if the publication allows it.
3. The publication's stored default, including a copied preset.
4. The type's stored default.
5. An empty editor with the required state visible.

A fixed publication value is supplied by the server and does not participate in this editable-field sequence. A user's edits, including clearing a value, must not trigger default initialization again. Existing schedules and replayed submissions use their stored values, never a subsequently changed personal default.

## One shared value editor

Build one recursive editor used by type previews, preset values, publication defaults and constants, catalog forms, and personal saved values.

| Value structure | Visual interaction |
| --- | --- |
| Scalar | Suitable text, number, Boolean, date/time, or choice control |
| Object | Labelled nested fields, expandable groups, field-specific errors |
| List | Repeated items with add, remove, and move actions |
| Named map | Editable keys and repeated typed values; block duplicate keys |
| Labelled structured choice | Choice selector returning the complete typed value; optional value preview |

Keep stable item identities while editing lists and map keys so focus does not jump. Show errors at the affected path, for example `rules[1].window`, and a concise summary linking to those controls. An unset Boolean must remain distinguishable from an explicit `false` when presence matters.

YAML is an alternative for structured data, not the fallback for unsupported nesting. Ordinary nested objects and collections must be fully editable visually.

## Visual and YAML synchronization

- Maintain one draft with a parsed semantic model and its source representation. Do not maintain unrelated visual and YAML copies with separate Save buttons.
- Visual changes patch the source through a syntax-aware document representation. Preserve field order, comments, and supported metadata. Do not silently discard unknown keys; retain them in an advanced section or report that a key prevents visual editing.
- YAML edits update the visual model only after parsing and validation. Invalid text stays in the editor with line and column errors; block saving and make clear that any preview is the last valid version.
- Switching modes must not save, discard edits, apply imports, or change publication revisions.
- Library editing validates the complete reference graph and dependent preset values. A selected-entry editor is a view over the existing library, not a second independent storage system.
- Keep the server authoritative for value validation, type resolution, permissions, and publication snapshots. Preserve the existing digest-based protection against concurrent overwrites.
- Invalid or conflicting saves retain the draft. **Save** runs validation; a separate validation action is optional. Show validation success in a green report and errors in a red report, with text and icons as well as color. Executing actions have a visible busy state and cannot be submitted twice.

## Backend and compatibility work required

This is more than a replacement text area. The current domain model and saved-value routes need extensions before the interface can offer the full workflow reliably.

1. Carry labels, help, examples, placeholder hints, explicit default presence, and nullability through parsing, resolution, validation, and frozen snapshots. Retain established primitive names and accept existing library documents.
2. Apply Single/List/Named map consistently at the root and within objects. Current nested schema support does not establish complete root-container behavior in publication and saved-value flows.
3. Add a personal-default marker with transactional enforcement of at most one default per owner, type identity or field identity, and shape. A compatible default is selected by validation, not only by a matching type name.
4. Permit personal saving of plain fields through a trusted server-derived built-in schema. The present saved-value API depends on a typed field schema; a UI checkbox alone cannot restore plain-field saving.
5. Preserve ownership checks and trusted server-selected schemas. Do not accept an arbitrary client schema as evidence that a saved value is valid.
6. Extend publication contracts, preview, submission, and generated frontend contracts together. Every persisted setting must have defined server behavior.
7. Keep resolved schema snapshots on publications and saved values. Show impact and support explicit republishing; do not introduce automatic mutation of existing publications or runs.
8. Add entry-level editing operations over the existing library document, using its digest and whole-library validation. Avoid introducing parallel YAML and database sources of truth or an unnecessary independent type-version lifecycle.

Earlier-project imports need explicit semantic conversion. In particular, preserve help and examples, convert the old `float` name deliberately, preserve the earlier required-field default when a flag is omitted, and explain how the old saved-case `multiple` policy maps to the new personal-saving policy. Preview unsupported metadata instead of silently dropping it. Personal-value database migration is a separate operation from shared-library import.

Python-class extraction remains opt-in. Select a configured execution environment, inspect a fully qualified class name through the existing inspection boundary, preview the extracted definition and warnings, then merge it into the draft. Do not import administrator-entered Python paths inside the web-server process or run repeated inspection on each keystroke.

## Delivery sequence

### Stage 1: Shared schema and recursive editor

Extend the canonical schema and generated contracts. Implement recursive objects, lists, and maps; typed choices; explicit missing/default/null states; and root shape validation. Use the editor in a type-preview vertical slice before replacing the full library page.

### Stage 2: Visual library and publication authoring

Implement type and preset list/detail screens, synchronized YAML, preview, usage information, and structured publication defaults/constants. Add root shape selection and richer field presentation. Relocate legacy imports to Data transfer. Preserve existing library content and publication snapshots.

### Stage 3: Personal values and defaults

Implement My saved values, case management, plain-field saving, compatibility reporting, and personal-default initialization. Reuse the same editor and picker in researcher forms. Test default precedence and ownership together with publication saving policies.

### Stage 4: Inspection, migration, and release

Add explicit class extraction and polish migration previews. Finish keyboard and narrow-screen behavior. Run backend, frontend, database-migration, and production-build checks, followed by a deployed end-to-end exercise. Update step-by-step user documentation with visual and YAML examples. Keep implementation status separate from those instructions.

## Acceptance examples

1. An administrator creates `ProcessingOptions` visually with a required integer `window`, a Boolean `enabled`, help text, and an example. No YAML entry is required.
2. A second type contains a list of `ProcessingOptions` and a named map of text values. Both have visual previews and fully editable values.
3. The administrator creates a `Standard options` preset and uses it in two publications: one editable and one fixed. Both receive the complete typed value; the fixed value cannot be overridden.
4. A researcher saves `Short windows` and `Long windows`, sets one as their default, edits it on My saved values, and reuses it in another compatible publication. Another user cannot read or modify either value.
5. A field-local plain integer can be saved when the publication permits it. A publication that disallows personal saving rejects a save request even if sent directly to the API.
6. Changing a type displays affected entries but does not change any existing publication or run. An incompatible saved case remains available against its original snapshot.
7. Switching Visual → YAML → Visual preserves values, comments, field order, and metadata. Invalid YAML is retained and cannot overwrite the last saved library.
8. Validation distinguishes missing values, `null`, `false`, `0`, empty strings, and empty collections. Duplicate map keys and invalid nested values produce precise errors.
9. An ordinary administrator can complete creation and publication without encountering an earlier-project format. A migrating administrator can preview conversion, resolve conflicts, and see unsupported semantics before saving.

Use focused domain and integration tests for these behaviors, with browser-level checks for mode switching, nested editing, keyboard focus, and the complete save/default/reuse journey. A static design prototype is not evidence that these behaviors are implemented.

## Source references

Earlier project:

- [Visual type library](../../../bioPipeline/frontend/src/components/pipelines/TypeLibraryPanel.tsx)
- [Recursive value editor](../../../bioPipeline/frontend/src/components/pipelines/TypedValueEditor.tsx)
- [Saved-case controls](../../../bioPipeline/frontend/src/components/pipelines/SavedCasesControl.tsx)
- [Saved Values page](../../../bioPipeline/frontend/src/app/saved-values/page.tsx)
- [Field and saved-value contracts](../../../bioPipeline/frontend/src/types/index.ts)
- [Published-job field editor](../../../bioPipeline/frontend/src/app/published-jobs-admin/page.tsx)
- [Type resolution](../../../bioPipeline/src/bio_pipeline_manager/type_schema.py)
- [Type-library update routes](../../../bioPipeline/backend/app/api/routes/type_library.py)

Current project:

- [Publication library screen](../../frontend/src/features/publications/PublicationLibraryScreen.tsx)
- [Current typed controls](../../frontend/src/features/values/TypedField.tsx)
- [Inline saved values](../../frontend/src/features/values/SavedValues.tsx)
- [Type domain](../../backend/app/domain/types.py)
- [Saved-value application service](../../backend/app/application/saved_values.py)
- [Saved-value routes](../../backend/app/api/v1/saved_values.py)
- [Publication responsibility and snapshot contract](publication-design.md)
