/**
 * The editor's own model of a publication being composed.
 *
 * Kept apart from the wire types because the two differ in a way that matters:
 * the API takes a list of fields, while the editor works in terms of *targets*
 * — everywhere in the pipeline a field could attach — and which of them are
 * currently exposed. Selecting and deselecting a target has to be
 * non-destructive, or unticking a box by accident loses the label somebody
 * just wrote.
 */

import type { BindableTarget, PrimitiveType, PublicationField } from "@/lib/api";
import type { PublicationFieldInput } from "@/lib/api";

export interface FieldDraft {
  exposed: boolean;
  label: string;
  helpText: string;
  group: string;
  required: boolean;
  fieldType: PrimitiveType;
}

/** A stable identity for a target, since it has no id of its own. */
export function targetId(target: BindableTarget): string {
  return [target.target, target.stage ?? "", target.step ?? "", target.key].join("|");
}

/** Turn a key like `experiment_folder` into "Experiment folder". */
export function humanise(key: string): string {
  const words = key.replace(/[_-]+/g, " ").trim();
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function typeFor(target: BindableTarget): PrimitiveType {
  switch (target.value_type) {
    case "file":
    case "directory":
    case "integer":
    case "number":
    case "boolean":
    case "object":
    case "array":
      return target.value_type;
    default:
      return "string";
  }
}

/**
 * The starting point for one target.
 *
 * An input the pipeline asks for starts **exposed and required**: it has no
 * default and materialisation refuses without it, so a publication that does
 * not supply it cannot run at all. A step parameter starts unexposed and
 * optional, because the pipeline already has a value for it — exposing one is
 * a deliberate choice to let somebody change it.
 */
export function initialDraft(target: BindableTarget): FieldDraft {
  const isPipelineInput = target.target === "default_value";
  return {
    exposed: isPipelineInput,
    label: humanise(target.key),
    helpText: "",
    group: "",
    required: isPipelineInput,
    fieldType: typeFor(target),
  };
}

/** What the exposed drafts look like to the API. */
export function toFieldInputs(
  targets: BindableTarget[],
  drafts: Record<string, FieldDraft>,
): PublicationFieldInput[] {
  return targets
    .map((target) => [target, drafts[targetId(target)]] as const)
    .filter((pair): pair is [BindableTarget, FieldDraft] => Boolean(pair[1]?.exposed))
    .map(([target, draft]) => ({
      key: target.key,
      label: draft.label.trim() || humanise(target.key),
      field_type: draft.fieldType,
      required: draft.required,
      ...(draft.helpText.trim() ? { help_text: draft.helpText.trim() } : {}),
      ...(draft.group.trim() ? { ui_group: draft.group.trim() } : {}),
      // The pipeline's current value becomes the form's default, so a
      // researcher who leaves a parameter alone gets what the author chose.
      ...(target.current_value !== null && target.current_value !== undefined
        ? { default_value: target.current_value }
        : {}),
      binding: {
        target: target.target,
        stage: target.stage ?? null,
        step: target.step ?? null,
        binding_key: target.key,
      },
    }));
}

/** What the preview should render, in the shape the researcher form expects. */
export function toPreviewFields(
  targets: BindableTarget[],
  drafts: Record<string, FieldDraft>,
): PublicationField[] {
  return toFieldInputs(targets, drafts).map((input, index) => ({
    key: input.key,
    label: input.label,
    field_type: input.field_type,
    required: input.required,
    help_text: input.help_text ?? null,
    placeholder: null,
    ui_group: input.ui_group ?? null,
    default_value: input.default_value ?? null,
    type_ref: null,
    source_policy: {},
    order_index: index,
  }));
}

/**
 * A slug the URL can carry, derived from the title.
 *
 * Derived rather than asked for: an admin naming a catalog entry is thinking
 * about the title, and a second nearly-identical box invites them to disagree
 * with themselves.
 */
export function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 128);
}

/** Targets grouped for display: what they are, in the order they matter. */
export function groupTargets(targets: BindableTarget[]) {
  const inputs = targets.filter((target) => target.target === "default_value");
  const stageInputs = targets.filter((target) => target.target === "stage_input");
  const parameters = targets.filter((target) => target.target === "step_parameter");
  return [
    {
      name: "Values the pipeline asks for",
      detail:
        "Every one of these must be supplied, so each is exposed by default. Fix one instead only if every run should use the same value.",
      targets: inputs,
    },
    { name: "Stage inputs", detail: "", targets: stageInputs },
    {
      name: "Step parameters",
      detail:
        "The pipeline already has a value for each of these. Expose one to let a researcher change it.",
      targets: parameters,
    },
  ].filter((group) => group.targets.length > 0);
}
