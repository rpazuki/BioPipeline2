import "@/test/next-navigation";

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PipelineEditorScreen } from "@/features/pipelines/PipelineEditorScreen";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";
import { router } from "@/test/next-navigation";

const COMPILED = {
  ok: true,
  graph_hash: "abcdef0123456789",
  inputs: [{ key: "sample_sheet", type: "file", required: true, default: null }],
  stages: [
    {
      key: "analyse",
      name: "analyse",
      variant: null,
      needs: [],
      fanout: "none",
      steps: ["load", "fit"],
      outputs: ["report"],
      task_class: "standard",
    },
  ],
  diagnostics: [],
};

const BROKEN = {
  ok: false,
  diagnostics: [
    {
      severity: "error",
      code: "reference.unresolvable",
      message: "No such value: {sample}",
      location: "stages.analyse.steps.load.params.path",
    },
    {
      severity: "error",
      code: "stage.duplicate_name",
      message: "Two stages are called 'analyse'.",
      location: "stages.1.name",
    },
  ],
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("compiling before storing", () => {
  it("will not store a revision that has never been compiled", () => {
    // A revision is immutable and permanent. Creating one that has not been
    // shown to the author is how a broken pipeline gets published.
    stubFetch([]);
    renderWithSession(<PipelineEditorScreen />, { user: ADMIN });
    expect(screen.getByRole("button", { name: "Create revision" })).toBeDisabled();
  });

  it("shows every problem at once, not the first", async () => {
    stubFetch([{ path: "/pipelines/compile-preview", method: "POST", body: BROKEN }]);
    renderWithSession(<PipelineEditorScreen />, { user: ADMIN });

    await userEvent.click(screen.getByRole("button", { name: "Compile" }));

    expect(await screen.findByText("No such value: {sample}")).toBeInTheDocument();
    expect(screen.getByText("Two stages are called 'analyse'.")).toBeInTheDocument();
    expect(screen.getByText("2 errors")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create revision" })).toBeDisabled();
  });

  it("locates each problem in the document", async () => {
    stubFetch([{ path: "/pipelines/compile-preview", method: "POST", body: BROKEN }]);
    renderWithSession(<PipelineEditorScreen />, { user: ADMIN });
    await userEvent.click(screen.getByRole("button", { name: "Compile" }));
    expect(
      await screen.findByText("stages.analyse.steps.load.params.path"),
    ).toBeInTheDocument();
  });

  it("shows the input contract and the stage graph once it compiles", async () => {
    stubFetch([{ path: "/pipelines/compile-preview", method: "POST", body: COMPILED }]);
    renderWithSession(<PipelineEditorScreen />, { user: ADMIN });

    await userEvent.click(screen.getByRole("button", { name: "Compile" }));

    expect(await screen.findByText("sample_sheet")).toBeInTheDocument();
    expect(screen.getByText("load → fit")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Create revision" })).toBeEnabled();
  });
});

describe("an edit made after compiling", () => {
  it("disables saving until the document is compiled again", async () => {
    // Otherwise the stored revision is not the one the author was shown.
    stubFetch([{ path: "/pipelines/compile-preview", method: "POST", body: COMPILED }]);
    renderWithSession(<PipelineEditorScreen />, { user: ADMIN });

    await userEvent.click(screen.getByRole("button", { name: "Compile" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Create revision" })).toBeEnabled(),
    );

    await userEvent.type(screen.getByLabelText("Pipeline document"), "\n# a change");

    expect(screen.getByRole("button", { name: "Create revision" })).toBeDisabled();
    expect(screen.getByText(/compile again before saving/i)).toBeInTheDocument();
  });
});

describe("storing a revision", () => {
  it("goes to the pipeline it created", async () => {
    stubFetch([
      { path: "/pipelines/compile-preview", method: "POST", body: COMPILED },
      {
        path: "/pipelines/revisions",
        method: "POST",
        status: 201,
        body: {
          revision_id: "00000000-0000-4000-8000-0000000000e1",
          pipeline_id: "00000000-0000-4000-8000-0000000000c2",
          version: 1,
          graph_hash: "abcdef0123456789",
          reused: false,
          warnings: [],
        },
      },
    ]);
    renderWithSession(<PipelineEditorScreen />, { user: ADMIN });

    await userEvent.click(screen.getByRole("button", { name: "Compile" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Create revision" })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Create revision" }));

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith(
        "/pipelines/00000000-0000-4000-8000-0000000000c2",
      ),
    );
  });
});
