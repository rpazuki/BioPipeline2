import "@/test/next-navigation";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PipelineDetailScreen } from "@/features/pipelines/PipelineDetailScreen";
import { ADMIN, renderWithSession, stubFetch, type Route } from "@/test/render";
import { router } from "@/test/next-navigation";

const PIPELINE_ID = "00000000-0000-4000-8000-0000000000c2";
const REVISION_ID = "00000000-0000-4000-8000-0000000000e1";

const REVISIONS: Route = {
  path: `/pipelines/${PIPELINE_ID}/revisions`,
  body: {
    items: [
      {
        revision_id: REVISION_ID,
        pipeline_id: PIPELINE_ID,
        version: 3,
        graph_hash: "abcdef0123456789",
        reused: false,
        warnings: [],
      },
    ],
  },
};

const SUBMITTED: Route = {
  path: "/runs",
  method: "POST",
  status: 201,
  body: {
    run_id: "00000000-0000-4000-8000-0000000000f1",
    task_count: 13,
    reused: false,
    warnings: [],
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function openSubmitDialog() {
  await userEvent.click(await screen.findByRole("button", { name: "Run…" }));
  return screen.findByRole("dialog");
}

describe("submitting a run", () => {
  it("carries an idempotency key, so a retried submit is not a second run", async () => {
    // On this hardware a duplicated RNA-seq alignment is a day of compute.
    const { calls } = stubFetch([REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    await openSubmitDialog();
    await userEvent.click(screen.getByRole("button", { name: "Submit run" }));

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    const submit = calls.find((call) => (call.init.method ?? "GET") === "POST");
    const headers = submit?.init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("goes straight to the run it created", async () => {
    stubFetch([REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    await openSubmitDialog();
    await userEvent.click(screen.getByRole("button", { name: "Submit run" }));

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/runs/00000000-0000-4000-8000-0000000000f1"),
    );
  });

  it("refuses to submit values that are not a JSON object", async () => {
    stubFetch([REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    const dialog = await openSubmitDialog();
    const values = screen.getByLabelText("Submitted values");
    await userEvent.clear(values);
    // Pasted rather than typed: user-event reads "[" as a key descriptor.
    await userEvent.click(values);
    await userEvent.paste("[1, 2]");

    expect(screen.getByText("Values must be a JSON object.")).toBeInTheDocument();
    expect(await within(dialog).findByRole("button", { name: "Submit run" })).toBeDisabled();
  });

  it("puts a rejected value on the field that carries it", async () => {
    stubFetch([
      REVISIONS,
      {
        path: "/runs",
        method: "POST",
        status: 422,
        body: {
          error: {
            code: "run.values_invalid",
            message: "Submitted values do not satisfy the input contract.",
            details: { errors: [{ path: "values", message: "sample_sheet is required" }] },
          },
        },
      },
    ]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    await openSubmitDialog();
    await userEvent.click(screen.getByRole("button", { name: "Submit run" }));

    expect(await screen.findByText("sample_sheet is required")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });
});

describe("revisions", () => {
  it("are shown with the graph hash that identifies what will run", async () => {
    stubFetch([REVISIONS]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });
    expect(await screen.findByText("v3")).toBeInTheDocument();
    expect(screen.getByText("abcdef012345")).toBeInTheDocument();
  });
});
