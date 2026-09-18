import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublishedForm, type Draft } from "@/features/catalog/components/PublishedForm";
import { renderWithSession, RESEARCHER, stubFetch, type Route } from "@/test/render";

const UPLOAD_ID = "00000000-0000-4000-8000-0000000000e1";

afterEach(() => vi.unstubAllGlobals());

function field(overrides: Record<string, unknown> = {}) {
  return {
    key: "sample",
    label: "Sample file",
    field_type: "file",
    required: true,
    default_value: null,
    help_text: null,
    placeholder: null,
    ui_group: null,
    source_policy: { sources: ["upload"] },
    ...overrides,
  };
}

const OPEN: Route = {
  path: "/uploads",
  method: "POST",
  status: 201,
  body: {
    id: UPLOAD_ID,
    filename: "plate.csv",
    status: "open",
    received_bytes: 0,
    chunk_max_bytes: 1024,
    expires_at: "2026-09-20T00:00:00Z",
    reference: null,
  },
};

const APPEND: Route = {
  path: `/uploads/${UPLOAD_ID}`,
  method: "PATCH",
  body: {
    id: UPLOAD_ID,
    filename: "plate.csv",
    status: "open",
    received_bytes: 7,
    chunk_max_bytes: 1024,
    expires_at: "2026-09-20T00:00:00Z",
  },
};

const COMPLETE: Route = {
  path: `/uploads/${UPLOAD_ID}/complete`,
  method: "POST",
  body: {
    id: UPLOAD_ID,
    filename: "plate.csv",
    status: "completed",
    received_bytes: 7,
    chunk_max_bytes: 1024,
    expires_at: "2026-09-20T00:00:00Z",
    artifact_id: "00000000-0000-4000-8000-0000000000c1",
    reference: `upload:${UPLOAD_ID}`,
  },
};

function form(
  draft: Draft,
  onChange: (key: string, value: string | boolean) => void,
  overrides = {},
) {
  return (
    <PublishedForm
      fields={[field(overrides)] as never}
      draft={draft}
      onChange={onChange}
      errorFor={() => undefined}
    />
  );
}

describe("choosing a file for a submission field", () => {
  it("sends it and hands the form the reference, not the filename", async () => {
    stubFetch([COMPLETE, OPEN, APPEND]);
    const onChange = vi.fn();
    const user = userEvent.setup();
    renderWithSession(form({ sample: "" }, onChange), { user: RESEARCHER });

    await user.upload(
      screen.getByLabelText("Sample file (required)"),
      new File(["od,0.4"], "plate.csv", { type: "text/csv" }),
    );

    // The field holds `upload:<id>`: the server resolves that to the path a
    // container reads, which this code has no business knowing.
    await waitFor(() => expect(onChange).toHaveBeenCalledWith("sample", `upload:${UPLOAD_ID}`));
  });

  it("names the file already chosen rather than showing a reference", async () => {
    stubFetch([
      {
        path: `/uploads/${UPLOAD_ID}`,
        body: {
          id: UPLOAD_ID,
          filename: "plate_01.csv",
          status: "completed",
          received_bytes: 2048,
          chunk_max_bytes: 1024,
          expires_at: "2026-09-20T00:00:00Z",
          reference: `upload:${UPLOAD_ID}`,
        },
      },
    ]);
    renderWithSession(form({ sample: `upload:${UPLOAD_ID}` }, vi.fn()), { user: RESEARCHER });

    expect(await screen.findByText("plate_01.csv")).toBeInTheDocument();
    expect(screen.getByText("(2.0 kB)")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Choose a different file" })).toBeInTheDocument();
  });

  it("says a failed transfer can be continued rather than repeated", async () => {
    stubFetch([
      { path: "/uploads", method: "POST", status: 201, body: OPEN.body },
      {
        path: `/uploads/${UPLOAD_ID}`,
        method: "PATCH",
        status: 422,
        body: {
          error: {
            code: "upload.invalid",
            message: "That file cannot be stored.",
            details: {},
          },
        },
      },
    ]);
    const user = userEvent.setup();
    renderWithSession(form({ sample: "" }, vi.fn()), { user: RESEARCHER });

    await user.upload(
      screen.getByLabelText("Sample file (required)"),
      new File(["od,0.4"], "plate.csv", { type: "text/csv" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("That file cannot be stored.");
    expect(alert).toHaveTextContent("continues from where it stopped");
  });

  it("offers the share as well when the field accepts both", async () => {
    stubFetch([]);
    renderWithSession(
      form({ sample: "" }, vi.fn(), { source_policy: { sources: ["upload", "shared"] } }),
      { user: RESEARCHER },
    );

    expect(screen.getByText(/name a file already on the share/)).toBeInTheDocument();
    expect(screen.getByLabelText("Path on a shared root")).toBeInTheDocument();
  });

  it("leaves a directory field as a path, because an upload is one file", async () => {
    stubFetch([]);
    renderWithSession(
      form({ sample: "" }, vi.fn(), {
        field_type: "directory",
        source_policy: { sources: ["upload", "shared"] },
      }),
      { user: RESEARCHER },
    );

    const control = screen.getByLabelText("Sample file (required)");
    expect(control).toHaveAttribute("type", "text");
  });
});
