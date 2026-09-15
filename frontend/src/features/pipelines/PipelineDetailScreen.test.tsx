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

function contract(
  inputs: unknown[] = [
    {
      key: "data_root",
      accept: "directory",
      sources: ["shared"],
      required: true,
      type_ref: null,
      help: null,
    },
  ],
  outputs: unknown[] = [
    {
      stage: "analyse",
      key: "report",
      path: "outputs/report.txt",
      delivery: ["download"],
      shared_root: null,
      retention_days: null,
      optional: false,
    },
  ],
): Route {
  return {
    path: `/pipelines/revisions/${REVISION_ID}`,
    body: {
      revision_id: REVISION_ID,
      pipeline_id: PIPELINE_ID,
      version: 3,
      graph_hash: "sha256:abcdef0123456789",
      created_at: "2026-03-01T09:00:00Z",
      validation_status: "valid",
      inputs,
      outputs,
    },
  };
}

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

describe("the submission form", () => {
  it("is built from the revision's own contract, not typed by hand", async () => {
    // The free-text box it replaced required the person filling it in to
    // already know the keys.
    stubFetch([contract(), REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    await openSubmitDialog();
    expect(await screen.findByLabelText("data_root (required)")).toBeInTheDocument();
    expect(screen.queryByLabelText("Submitted values")).not.toBeInTheDocument();
  });

  it("says what kind of thing each input wants, and where it may come from", async () => {
    stubFetch([contract(), REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    await openSubmitDialog();
    expect(await screen.findByText("A directory in shared storage.")).toBeInTheDocument();
  });

  it("will not submit while a required input is empty", async () => {
    stubFetch([contract(), REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    const dialog = await openSubmitDialog();
    await screen.findByLabelText("data_root (required)");
    expect(within(dialog).getByRole("button", { name: "Submit run" })).toBeDisabled();
  });

  it("sends what was typed, under the key the contract named", async () => {
    const { calls } = stubFetch([contract(), REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    const dialog = await openSubmitDialog();
    await userEvent.type(
      await screen.findByLabelText("data_root (required)"),
      "/mnt/lab/experiments",
    );
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit run" }));

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    const post = calls.find((call) => (call.init.method ?? "GET") === "POST");
    expect(JSON.parse(String(post?.init.body))).toMatchObject({
      pipeline_revision_id: REVISION_ID,
      values: { data_root: "/mnt/lab/experiments" },
    });
  });

  it("carries an idempotency key, so a retried submit is not a second run", async () => {
    const { calls } = stubFetch([contract(), REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    const dialog = await openSubmitDialog();
    await userEvent.type(await screen.findByLabelText("data_root (required)"), "/mnt/lab");
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit run" }));

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    const post = calls.find((call) => (call.init.method ?? "GET") === "POST");
    const headers = post?.init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("puts a rejected value on the input that carries it", async () => {
    stubFetch([
      contract(),
      REVISIONS,
      {
        path: "/runs",
        method: "POST",
        status: 422,
        body: {
          error: {
            code: "run.values_invalid",
            message: "Submitted values do not satisfy the input contract.",
            details: { errors: [{ path: "inputs.data_root", message: "must be a path" }] },
          },
        },
      },
    ]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    const dialog = await openSubmitDialog();
    const field = await screen.findByLabelText("data_root (required)");
    await userEvent.type(field, "x");
    await userEvent.click(within(dialog).getByRole("button", { name: "Submit run" }));

    const message = await screen.findByText("must be a path");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field.getAttribute("aria-describedby")).toContain(message.id);
    expect(router.push).not.toHaveBeenCalled();
  });

  it("submits straight away when a pipeline asks for nothing", async () => {
    stubFetch([contract([], []), REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    const dialog = await openSubmitDialog();
    expect(await screen.findByText(/takes no submitted values/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Submit run" })).toBeEnabled();
  });

  it("admits when a structured type is beyond it, rather than pretending", async () => {
    stubFetch([
      contract([
        {
          key: "settings",
          accept: "value",
          sources: [],
          required: false,
          type_ref: "GrowthSettings",
          help: null,
        },
      ]),
      REVISIONS,
      SUBMITTED,
    ]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    await openSubmitDialog();
    expect(await screen.findByText(/the type library is not served yet/i)).toBeInTheDocument();
  });

  it("shows what the run will produce before it is started", async () => {
    stubFetch([contract(), REVISIONS, SUBMITTED]);
    renderWithSession(<PipelineDetailScreen pipelineId={PIPELINE_ID} />, { user: ADMIN });

    await openSubmitDialog();
    await userEvent.click(await screen.findByText("What this produces"));
    expect(screen.getByText("report")).toBeInTheDocument();
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
