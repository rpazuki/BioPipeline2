# Define and publish reusable values

## 1. Define administrator types and presets

1. Sign in as an administrator.
2. Open **Publications → Types and presets**.
3. Keep **Types → Visual** selected and click **New type**.
4. Enter an identifier such as `ProcessingOptions` and a display name.
5. Select **Object with fields**. Rename the initial `value` field to `window`
   and select Integer and Required. Add `normalize` as a Boolean with default
   `true`. Add labels, help, and examples
   in the field inspector. Use **Field shape** for a list or named map.
6. Check **Form preview**, then click **Save library**. Saving validates the
   whole library, including references and preset values.
7. Open **Shared presets**, click **New preset**, select `ProcessingOptions`,
   and enter `window = 5` and `normalize = true` using the visual controls.
8. Save the library.

To edit source instead, select **YAML**. The following example defines the
same types and values, plus labelled object choices. For an empty library,
paste the entire example. For an existing library, merge the
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

1. Click **Validate** if you want a separate validation report.
2. Correct any reported errors, then click **Save library**.

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

To enter a constant directly, select **Enter a value directly**, select its
type, enable **Supply a fixed value**, and fill the visual value editor.
Select **YAML value** to edit the same structured value as source. Expand
**Value shape and personal saving** to choose Single, List, or Named map.
To use `null`, enable **Allow null** and select **Use null** in the value
editor. Leaving the supplied-value option unchecked means no value is set.

## 5. Publish labelled object choices

1. Create another entry using the same pipeline revision.
2. Include `config` and choose **Ask the researcher**.
3. Keep **Library preset** set to **Enter a value directly**.
4. Select `ProcessingChoice` in **Library type**.
5. Leave **Supply an editable default** unchecked, or enable it and select a choice.
6. Confirm the preview offers `Standard` and `Wide window`.
7. Publish, select a choice in **Catalog**, and submit a run.

## 6. Update the library

1. Open **Publications → Types and presets** and select the type or preset.
2. Edit it visually or select **YAML**, then save it.
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

## 7. Manage personal saved values

1. When publishing a field, expand **Value shape and personal saving**.
2. Set **Personal saving** to **Allow personal saved values**, or keep
   **Automatic for typed fields** when a type is supplied by the pipeline.
3. Enable **Allow a personal default** if the researcher's own default should
   initialize a new form before the publication default.
4. Publish the entry.
5. As a researcher, fill the field in Catalog and click **Save this value**.
6. Enter a name and click **Keep it**.
7. Open **My saved values**, select the type and named value, and edit it
   using the visual fields. **YAML value** is available only to administrators.
8. Click **Save value**. Use **Set as my default** to choose one default for
   that type and shape. Use **Duplicate** to make another named case.
9. Open a compatible catalog entry. Select a saved case or edit the initialized
   personal default. Clearing or changing it does not load the default again.

To create a case outside a run form, open **My saved values → New saved value**,
choose a published field, enter a name and value, and click **Save personal value**.
Private saved values belong to the signed-in user. Existing runs and schedules
keep their recorded inputs when a personal default changes.

## 8. Extract a type from a Python class

1. Open **Types and presets → More → Extract from a Python class**.
2. Select an execution environment containing the installed Python module.
3. Enter a fully qualified name, such as `package.module.Options`.
4. Click **Preview extracted type**.
5. Review the definitions and warnings. Default factories are not run and
   custom model validators must be reviewed separately.
6. Click **Add reviewed definitions to draft**, inspect the visual editor or
   YAML, and save the library.

For native preset imports, use **Types and presets → More → Presets to import**.
For conversion from an earlier deployment, follow [Data transfer](data-transfer.md).

For local folders, ZIP inputs and result downloads, follow
[Publication transfers](publication-transfers.md).
