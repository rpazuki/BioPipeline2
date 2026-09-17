import { describe, expect, it } from "vitest";

import {
  groupTargets,
  humanise,
  initialDraft,
  slugify,
  targetId,
  toFieldInputs,
  toPreviewFields,
  type FieldDraft,
} from "@/features/publications/model";
import type { BindableTarget } from "@/lib/api";

const PIPELINE_INPUT: BindableTarget = {
  target: "default_value",
  stage: null,
  step: null,
  key: "data_root",
  value_type: "directory",
  current_value: null,
};

const PARAMETER: BindableTarget = {
  target: "step_parameter",
  stage: "fit",
  step: "df_fit_max_growth_rate",
  key: "moving_window_size",
  value_type: "integer",
  current_value: 5,
};

function drafts(entries: [BindableTarget, Partial<FieldDraft>][]) {
  const composed: Record<string, FieldDraft> = {};
  for (const [target, overrides] of entries) {
    composed[targetId(target)] = { ...initialDraft(target), ...overrides };
  }
  return composed;
}

describe("what starts exposed", () => {
  it("exposes a value the pipeline asks for, because it has no other source", () => {
    // A public input is `$WILL_PROVIDE$`: materialisation refuses without it,
    // so a publication that does not supply it cannot run at all.
    expect(initialDraft(PIPELINE_INPUT).exposed).toBe(true);
    expect(initialDraft(PIPELINE_INPUT).required).toBe(true);
  });

  it("leaves a step parameter alone, because the pipeline already has a value", () => {
    expect(initialDraft(PARAMETER).exposed).toBe(false);
    expect(initialDraft(PARAMETER).required).toBe(false);
  });

  it("takes the field type from the value that is there", () => {
    expect(initialDraft(PARAMETER).fieldType).toBe("integer");
    expect(initialDraft(PIPELINE_INPUT).fieldType).toBe("directory");
  });

  it("suggests a label a person would write", () => {
    expect(humanise("experiment_folder")).toBe("Experiment folder");
    expect(initialDraft(PARAMETER).label).toBe("Moving window size");
  });
});

describe("what gets sent", () => {
  it("includes only the exposed targets", () => {
    const fields = toFieldInputs(
      [PIPELINE_INPUT, PARAMETER],
      drafts([
        [PIPELINE_INPUT, {}],
        [PARAMETER, { exposed: false }],
      ]),
    );
    expect(fields.map((field) => field.key)).toEqual(["data_root"]);
  });

  it("carries the binding coordinates the target came with", () => {
    const [field] = toFieldInputs([PARAMETER], drafts([[PARAMETER, { exposed: true }]]));
    expect(field!.binding).toEqual({
      target: "step_parameter",
      stage: "fit",
      step: "df_fit_max_growth_rate",
      binding_key: "moving_window_size",
    });
  });

  it("makes the pipeline's current value the form's default", () => {
    // So a researcher who leaves a parameter alone gets what the author chose.
    const [field] = toFieldInputs([PARAMETER], drafts([[PARAMETER, { exposed: true }]]));
    expect(field!.default_value).toBe(5);
  });

  it("falls back to a humanised key when the label is emptied", () => {
    const [field] = toFieldInputs(
      [PARAMETER],
      drafts([[PARAMETER, { exposed: true, label: "   " }]]),
    );
    expect(field!.label).toBe("Moving window size");
  });

  it("omits empty help text and groups rather than sending blanks", () => {
    const [field] = toFieldInputs([PARAMETER], drafts([[PARAMETER, { exposed: true }]]));
    expect(field).not.toHaveProperty("help_text");
    expect(field).not.toHaveProperty("ui_group");
  });
});

describe("the preview", () => {
  it("describes the same fields the API will be given", () => {
    const state = drafts([
      [PIPELINE_INPUT, { label: "Experiment folder" }],
      [PARAMETER, { exposed: true, label: "Smoothing window", group: "Fitting" }],
    ]);
    const preview = toPreviewFields([PIPELINE_INPUT, PARAMETER], state);
    expect(preview.map((field) => field.label)).toEqual([
      "Experiment folder",
      "Smoothing window",
    ]);
    expect(preview[1]!.ui_group).toBe("Fitting");
    expect(preview[1]!.default_value).toBe(5);
  });
});

describe("the address", () => {
  it("is derived from the title, so nobody has to agree with themselves twice", () => {
    expect(slugify("OD600 growth rates")).toBe("od600-growth-rates");
  });

  it("drops punctuation that has no business in a URL", () => {
    expect(slugify("  RNA-seq: align & count!  ")).toBe("rna-seq-align-count");
  });
});

describe("grouping", () => {
  it("puts what the pipeline demands first", () => {
    const groups = groupTargets([PARAMETER, PIPELINE_INPUT]);
    expect(groups[0]!.name).toBe("Values the pipeline asks for");
  });

  it("omits a group with nothing in it", () => {
    expect(groupTargets([PIPELINE_INPUT]).map((group) => group.name)).toEqual([
      "Values the pipeline asks for",
    ]);
  });
});
