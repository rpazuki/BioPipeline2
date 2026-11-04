# Define and publish reusable values

## 1. Define administrator types and presets

1. Sign in as an administrator.
2. Open **Publications → Types and presets**.
3. For an empty library, paste this YAML. For an existing library, merge the
   entries into its `definitions` and `presets` mappings:

```yaml
definitions:
  ProcessingOptions:
    fields:
      window: {type: integer, required: true}
      normalize: {type: boolean, default: true}
  ProcessingChoice:
    type: enum
    options:
      - label: Standard
        value: {window: 5, normalize: true}
      - label: Wide window
        value: {window: 11, normalize: true}
  WindowSize:
    type: integer
presets:
  standard_options:
    type_ref: ProcessingOptions
    value: {window: 5, normalize: true}
  standard_window:
    type_ref: WindowSize
    value: 5
```

4. Click **Validate**. Correct any reported errors.
5. Click **Save library**.

`ProcessingOptions` describes an object with an integer field and a Boolean
field. `standard_options` is a named value of that type. `ProcessingChoice`
provides two labelled choices; each returns an entire object.

## 2. Save a pipeline that accepts the value

1. Open **Pipelines → Pipelines → New pipeline**.
2. Paste this YAML:

```yaml
pipeline: publication_options_demo
title: Publication options demonstration
defaults:
  config: $WILL_PROVIDE$
inputs:
  config:
    accept: value
stages:
  - name: process
    steps:
      - name: result
        package: builtins
        method: str
        parameters:
          object: "{config}"
```

3. Compile and save the revision.

This example converts the submitted object to a string. It needs no additional
Python package and declares no downloadable output files. The publication
defines how the `config` value is entered.

## 3. Publish an editable preset

1. Open **Publications → New entry**.
2. Select the demonstration pipeline and its saved revision.
3. Enter a title such as `Editable processing options`.
4. Keep `config` included.
5. Under **Value supplied by**, select **Ask the researcher**.
6. Under **Library preset**, select `standard_options`.
7. Confirm the preview contains `window` and `normalize` controls initialized
   to `5` and `true`.
8. Click **Publish**.
9. Open the entry in **Catalog**, edit the fields if desired, and submit a run.

## 4. Publish a constant

1. Create another entry using the same pipeline revision.
2. Select `standard_options` as the preset for `config`.
3. Select **Fixed value (hidden from form)**.
4. Confirm `config` is absent from the researcher preview.
5. Publish and submit a run without entering `config`.

The submitted computation receives the stored object. A request that attempts
to replace a fixed value with a different value is rejected.

To enter a constant directly, select **Enter a value directly** and fill the
value box. This box uses JavaScript Object Notation (JSON): examples are `5`,
`false`, `"text"`, and `{"window": 5, "normalize": true}`. Select a library type
to validate the literal against that definition. An empty box means no
default; `null` is not a supplied constant.

## 5. Publish labelled object choices

1. Create another entry using the same pipeline revision.
2. Include `config` and choose **Ask the researcher**.
3. Keep **Library preset** set to **Enter a value directly**.
4. Select `ProcessingChoice` in **Library type**.
5. Leave the editable default empty, or enter one of the exact option objects.
6. Confirm the preview offers `Standard` and `Wide window`.
7. Publish, select a choice in **Catalog**, and submit a run.

## 6. Update the library

1. Open **Publications → Types and presets** and edit the source.
2. Validate and save it.
3. Create a new publication revision to use the changed definitions.

Existing publications keep their stored types and values. If another
administrator changes the library while a publication is being composed, click
**Refresh types and presets** in the publication editor and check the preview
before publishing again. The publication draft remains in the editor.

If another
administrator saved while the editor was open, copy any edits you want to
retain, click **Discard edits and reload**, then apply and validate them again.

For API publication requests, fetch `/api/v1/publication-library` and send its
`digest` as `library_digest`. A field can select `type_ref` or `preset_ref`.
For a preset, omit literal `default_value` and `fixed_value`; set
`visibility: hidden` to use it as a constant. Otherwise it becomes an editable
default. The server resolves the preset and stores the value and schema.

## 7. Import old administrator definitions

1. Open **Publications → Types and presets**.
2. Expand **Import existing types or named values**.
3. Select the appropriate import format:
   - **Old project type library:** paste the old `type_library.yaml` mapping.
   - **Old job defaults and named variants:** paste the old job definition or
     a mapping containing its `defaults` and `variables` sections.
   - **Named presets with type references:** paste a mapping of preset names to
     `type_ref` and `value` entries.
4. Paste the source into **Source to import**.
5. Click **Preview merge into editor**.
6. Review the merged YAML and the import notes. Rename conflicting entries
   before importing them; existing names are not overwritten.
7. Click **Validate**, then **Save library**.

For example, import these old job constants and variants:

```yaml
defaults:
  window: 5
variables:
  processing:
    standard: {window: 5, normalize: true}
    wide: {window: 11, normalize: true}
```

This creates a `window` preset and two object-valued presets,
`processing_standard` and `processing_wide`. The processing type offers the
two named variants as choices.

Old `float` members become `number`. Old path-like members become ordinary
string values; choose actual upload or shared-storage methods in the
publication. Python class references, input preprocessing functions, and
output serializers are not executed by this import. Unresolved input markers
are omitted and listed in the preview notes.

Researcher-owned saved values are not automatically made into administrator
presets. To promote an explicitly selected value, first define or import its
type, then import a named preset containing its type reference and value.

For local folders, ZIP inputs and result downloads, follow
[Publication transfers](publication-transfers.md).
