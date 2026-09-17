import "@/test/next-navigation";

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PublicationEditorScreen } from "@/features/publications/PublicationEditorScreen";
import { ADMIN, renderWithSession, stubFetch, type Route } from "@/test/render";
import { router } from "@/test/next-navigation";

const PIPELINE_ID = "00000000-0000-4000-8000-0000000000c2";
const REVISION_ID = "00000000-0000-4000-8000-0000000000e1";

const PIPELINES: Route = {
  path: "/pipelines",
  body: {
    items: [
      {
        id: PIPELINE_ID,
        slug: "od600",
        title: "OD600 growth rates",
        status: "active",
        created_at: "2026-03-01T09:00:00Z",
      },
    ],
  },
};

const REVISIONS: Route = {
  path: `/pipelines/${PIPELINE_ID}/revisions`,
  body: {
    items: [
      {
        revision_id: REVISION_ID,
        pipeline_id: PIPELINE_ID,
        version: 3,
        graph_hash: "sha256:abcdef",
        reused: false,
        warnings: [],
      },
    ],
  },
};

const BINDABLE: Route = {
  path: `/pipelines/revisions/${REVISION_ID}/bindable`,
  body: {
    items: [
      {
        target: "default_value",
        stage: null,
        step: null,
        key: "data_root",
        value_type: "directory",
        current_value: null,
      },
      {
        target: "step_parameter",
        stage: "fit",
        step: "df_fit_max_growth_rate",
        key: "moving_window_size",
        value_type: "integer",
        current_value: 5,
      },
    ],
    total: 2,
  },
};

const CREATED: Route = {
  path: "/publications/revisions",
  method: "POST",
  status: 201,
  body: {
    publication_id: "00000000-0000-4000-8000-0000000000a1",
    revision_id: "00000000-0000-4000-8000-0000000000b1",
    version: 1,
    warnings: [],
  },
};

const PUBLISHED: Route = {
  path: "/publications/00000000-0000-4000-8000-0000000000a1/publish",
  method: "POST",
  body: { id: "x", slug: "s", status: "published", current_revision_id: null, created_at: "x" },
};

const ROUTES = [BINDABLE, REVISIONS, PIPELINES, CREATED, PUBLISHED];

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

async function chooseRevision() {
  // Wait for each list to arrive before choosing from it: the selects render
  // before their options do.
  await screen.findByRole("option", { name: "OD600 growth rates" });
  await userEvent.selectOptions(screen.getByLabelText("Pipeline"), PIPELINE_ID);
  await screen.findByRole("option", { name: "v3" });
  await userEvent.selectOptions(screen.getByLabelText("Revision"), REVISION_ID);
}

describe("choosing what to expose", () => {
  it("offers the targets the revision actually has", async () => {
    stubFetch(ROUTES);
    renderWithSession(<PublicationEditorScreen />, { user: ADMIN });
    await chooseRevision();

    expect(await screen.findByText("data_root")).toBeInTheDocument();
    expect(screen.getByText("moving_window_size")).toBeInTheDocument();
  });

  it("shows where a parameter lives and what it is today", async () => {
    // An admin deciding whether to let researchers change this needs both.
    stubFetch(ROUTES);
    renderWithSession(<PublicationEditorScreen />, { user: ADMIN });
    await chooseRevision();

    expect(await screen.findByText("fit · df_fit_max_growth_rate")).toBeInTheDocument();
    expect(screen.getByText("now 5")).toBeInTheDocument();
  });

  it("exposes what the pipeline demands and leaves parameters alone", async () => {
    stubFetch(ROUTES);
    renderWithSession(<PublicationEditorScreen />, { user: ADMIN });
    await chooseRevision();

    await screen.findByText("data_root");
    expect(screen.getByRole("checkbox", { name: "data_root" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "moving_window_size" })).not.toBeChecked();
  });
});

describe("the preview", () => {
  it("is the researcher's form, updating as the entry is composed", async () => {
    stubFetch(ROUTES);
    renderWithSession(<PublicationEditorScreen />, { user: ADMIN });
    await chooseRevision();

    await screen.findByText("data_root");
    expect(screen.getByLabelText("Data root (required)")).toBeInTheDocument();

    const label = screen.getAllByLabelText("Label")[0]!;
    await userEvent.clear(label);
    await userEvent.type(label, "Experiment folder");

    expect(await screen.findByLabelText("Experiment folder (required)")).toBeInTheDocument();
  });

  it("gains a field the moment one is exposed", async () => {
    stubFetch(ROUTES);
    renderWithSession(<PublicationEditorScreen />, { user: ADMIN });
    await chooseRevision();

    await screen.findByText("moving_window_size");
    expect(screen.queryByLabelText("Moving window size")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("checkbox", { name: "moving_window_size" }));
    expect(await screen.findByLabelText("Moving window size")).toBeInTheDocument();
  });
});

describe("the address", () => {
  it("is derived from the title", async () => {
    stubFetch(ROUTES);
    renderWithSession(<PublicationEditorScreen />, { user: ADMIN });
    await chooseRevision();

    await userEvent.type(await screen.findByLabelText("Title"), "OD600 growth rates");
    expect(await screen.findByText("/catalog/od600-growth-rates")).toBeInTheDocument();
  });
});

describe("publishing", () => {
  it("sends the bindings the targets came with, then opens the entry", async () => {
    const { calls } = stubFetch(ROUTES);
    renderWithSession(<PublicationEditorScreen />, { user: ADMIN });
    await chooseRevision();

    await userEvent.type(await screen.findByLabelText("Title"), "OD600 growth rates");
    await userEvent.click(screen.getByRole("checkbox", { name: "moving_window_size" }));
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    await waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/catalog/od600-growth-rates"),
    );

    const post = calls.find((call) => call.url.includes("/publications/revisions"));
    const body = JSON.parse(String(post?.init.body));
    expect(body.slug).toBe("od600-growth-rates");
    expect(body.fields).toHaveLength(2);
    expect(body.fields[1].binding).toEqual({
      target: "step_parameter",
      stage: "fit",
      step: "df_fit_max_growth_rate",
      binding_key: "moving_window_size",
    });
  });

  it("will not publish without a title", async () => {
    stubFetch(ROUTES);
    renderWithSession(<PublicationEditorScreen />, { user: ADMIN });
    await chooseRevision();

    await screen.findByText("data_root");
    expect(screen.getByRole("button", { name: "Publish" })).toBeDisabled();
  });

  it("reports a refused publish rather than navigating", async () => {
    stubFetch([
      BINDABLE,
      REVISIONS,
      PIPELINES,
      {
        path: "/publications/revisions",
        method: "POST",
        status: 422,
        body: {
          error: {
            code: "publication.invalid",
            message: "The publication could not be created: 1 error(s).",
            details: {
              errors: [
                {
                  severity: "error",
                  code: "publication.input_not_covered",
                  message: "The pipeline asks for 'mapping_yaml' and no field supplies it.",
                  location: "mapping_yaml",
                },
              ],
            },
          },
        },
      },
    ]);
    renderWithSession(<PublicationEditorScreen />, { user: ADMIN });
    await chooseRevision();

    await userEvent.type(await screen.findByLabelText("Title"), "Incomplete");
    await userEvent.click(screen.getByRole("button", { name: "Publish" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("mapping_yaml");
    expect(router.push).not.toHaveBeenCalled();
  });
});
