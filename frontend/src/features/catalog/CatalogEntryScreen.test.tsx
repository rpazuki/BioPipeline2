import "@/test/next-navigation";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { CatalogEntryScreen } from "@/features/catalog/CatalogEntryScreen";
import { RESEARCHER, renderWithSession, stubFetch, type Route } from "@/test/render";
import { router } from "@/test/next-navigation";

const SLUG = "od600-growth-rates";

function entry(fields: unknown[]): Route {
  return {
    path: `/catalog/${SLUG}`,
    body: {
      slug: SLUG,
      title: "OD600 growth rates",
      description: "Fit growth curves from plate-reader exports.",
      version: 2,
      publication_id: "00000000-0000-4000-8000-0000000000a1",
      revision_id: "00000000-0000-4000-8000-0000000000b1",
      fields,
    },
  };
}

const FOLDER = {
  key: "experiment_folder",
  label: "Experiment folder",
  field_type: "directory",
  required: true,
  help_text: null,
  placeholder: null,
  ui_group: null,
  default_value: null,
  type_ref: null,
  source_policy: { sources: ["shared"] },
  order_index: 0,
};

const WINDOW = {
  key: "window",
  label: "Smoothing window",
  field_type: "integer",
  required: false,
  help_text: "How many points the fit averages over.",
  placeholder: null,
  ui_group: null,
  default_value: 5,
  type_ref: null,
  source_policy: {},
  order_index: 1,
};

const STARTED: Route = {
  path: `/catalog/${SLUG}/runs`,
  method: "POST",
  status: 201,
  body: {
    run_id: "00000000-0000-4000-8000-0000000000f1",
    task_count: 4,
    reused: false,
    warnings: [],
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("the published form", () => {
  it("is rendered in the admin's words, not the pipeline's", async () => {
    stubFetch([entry([FOLDER, WINDOW]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });

    expect(await screen.findByLabelText("Experiment folder (required)")).toBeInTheDocument();
    expect(screen.getByLabelText("Smoothing window")).toBeInTheDocument();
    expect(screen.getByText("How many points the fit averages over.")).toBeInTheDocument();
  });

  it("names nothing a researcher should not have to know about", async () => {
    stubFetch([entry([FOLDER, WINDOW]), STARTED]);
    const { container } = renderWithSession(<CatalogEntryScreen slug={SLUG} />, {
      user: RESEARCHER,
    });
    await screen.findByLabelText("Experiment folder (required)");
    expect(container.textContent).not.toMatch(/stage|step|revision id|binding/i);
  });

  it("starts a field at its published default", async () => {
    stubFetch([entry([FOLDER, WINDOW]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });
    expect(await screen.findByLabelText("Smoothing window")).toHaveValue(5);
  });

  it("says where a path may come from when there is no UI for it yet", async () => {
    stubFetch([entry([FOLDER]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });
    expect(await screen.findByText("A directory in shared storage.")).toBeInTheDocument();
  });
});

describe("types", () => {
  it("sends a number as a number, not as a string", async () => {
    // The published field type is the first point in the system that knows
    // this value is an integer; the platform has no coercion step behind it.
    const { calls } = stubFetch([entry([FOLDER, WINDOW]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });

    await userEvent.type(
      await screen.findByLabelText("Experiment folder (required)"),
      "/mnt/lab/run7",
    );
    await userEvent.click(screen.getByRole("button", { name: "Review and start" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Start run" }),
    );

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    const post = calls.find((call) => (call.init.method ?? "GET") === "POST");
    expect(JSON.parse(String(post?.init.body))).toEqual({
      values: { experiment_folder: "/mnt/lab/run7", window: 5 },
    });
  });

  it("refuses a whole-number field that was given a fraction", async () => {
    stubFetch([entry([FOLDER, WINDOW]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });

    const field = await screen.findByLabelText("Smoothing window");
    await userEvent.clear(field);
    await userEvent.type(field, "2.5");
    await userEvent.click(screen.getByRole("button", { name: "Review and start" }));

    expect(await screen.findByText("This must be a whole number.")).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("starting a run", () => {
  it("confirms the values before spending a day of compute", async () => {
    stubFetch([entry([FOLDER, WINDOW]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });

    await userEvent.type(
      await screen.findByLabelText("Experiment folder (required)"),
      "/mnt/lab/run7",
    );
    await userEvent.click(screen.getByRole("button", { name: "Review and start" }));

    const dialog = await screen.findByRole("dialog");
    // The path as typed, not as JSON: the point of repeating values back is
    // that somebody checks them, and quotes around a path are noise.
    expect(within(dialog).getByText("/mnt/lab/run7")).toBeInTheDocument();
  });

  it("does not nag about a required field before the form is used", async () => {
    stubFetch([entry([FOLDER]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });
    await screen.findByLabelText("Experiment folder (required)");
    expect(screen.queryByText(/is required/)).not.toBeInTheDocument();
  });

  it("says what is missing once somebody tries", async () => {
    stubFetch([entry([FOLDER]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });

    await screen.findByLabelText("Experiment folder (required)");
    await userEvent.click(screen.getByRole("button", { name: "Review and start" }));
    expect(await screen.findByText("Experiment folder is required.")).toBeInTheDocument();
  });

  it("goes to the run it started", async () => {
    stubFetch([entry([FOLDER]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });

    await userEvent.type(
      await screen.findByLabelText("Experiment folder (required)"),
      "/mnt/lab/run7",
    );
    await userEvent.click(screen.getByRole("button", { name: "Review and start" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Start run" }),
    );

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/runs/00000000-0000-4000-8000-0000000000f1"),
    );
  });

  it("carries an idempotency key, so a retry is not a second run", async () => {
    const { calls } = stubFetch([entry([FOLDER]), STARTED]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });

    await userEvent.type(
      await screen.findByLabelText("Experiment folder (required)"),
      "/mnt/lab/run7",
    );
    await userEvent.click(screen.getByRole("button", { name: "Review and start" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Start run" }),
    );

    await waitFor(() => expect(router.push).toHaveBeenCalled());
    const post = calls.find((call) => (call.init.method ?? "GET") === "POST");
    const headers = post?.init.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("puts a server-side rejection on the field that caused it", async () => {
    stubFetch([
      entry([FOLDER]),
      {
        path: `/catalog/${SLUG}/runs`,
        method: "POST",
        status: 422,
        body: {
          error: {
            code: "catalog.values_invalid",
            message: "The submitted values do not satisfy this catalog entry.",
            details: {
              errors: [
                { path: "values.experiment_folder", message: "That folder does not exist." },
              ],
            },
          },
        },
      },
    ]);
    renderWithSession(<CatalogEntryScreen slug={SLUG} />, { user: RESEARCHER });

    const field = await screen.findByLabelText("Experiment folder (required)");
    await userEvent.type(field, "/mnt/nope");
    await userEvent.click(screen.getByRole("button", { name: "Review and start" }));
    await userEvent.click(
      within(await screen.findByRole("dialog")).getByRole("button", { name: "Start run" }),
    );

    expect(await screen.findByText("That folder does not exist.")).toBeInTheDocument();
    expect(router.push).not.toHaveBeenCalled();
  });
});
