# Transfer shared definitions and values

## 1. Import earlier BioPipeline definitions

1. Sign in as an administrator and open **Administration → Data transfer**.
2. Select **Earlier BioPipeline type definitions** for a `type_library.yaml`
   mapping, or **Earlier BioPipeline shared defaults and choices** for a job
   definition containing `defaults` and `variables`.
3. Paste the source into **Source to import**.
4. Click **Preview conversion**.
5. Review **Merged library preview** and all conversion notes. Resolve name
   conflicts in the source before trying again; existing names are not replaced.
6. Click **Save reviewed conversion**.
7. Open **Types and presets** and inspect the resulting definitions and presets.
8. Select the imported type or preset when creating a new publication revision.

For example, import these shared defaults and named alternatives:

```yaml
defaults:
  window: 5
variables:
  processing:
    standard: {window: 5, normalize: true}
    wide: {window: 11, normalize: true}
```

The result contains the presets `window`, `processing_standard`, and
`processing_wide`. A choice type contains the two processing alternatives.

Conversion maps `float` to `number`, retains field documentation, and makes
the earlier omitted required-field setting explicit. File-like members become
text values; choose actual file transfers in the publication. Python source
references, preprocessing functions, and output serializers are not executed.
Unsupported metadata and unresolved references appear in the conversion notes.

This workflow transfers shared configuration. It does not import complete jobs
or convert private user values into shared presets. Existing publications keep
their stored type and value snapshots.

## 2. Import native presets

1. Open **Publications → Types and presets → More**.
2. Paste a mapping containing type references and values into **Presets to import**:

```yaml
presets:
  standard_window:
    type_ref: WindowSize
    value: 5
```

3. Click **Preview preset import**.
4. Review the merged draft in Visual or YAML mode.
5. Click **Save library**.

Create or import the referenced `WindowSize` type before importing this example.
