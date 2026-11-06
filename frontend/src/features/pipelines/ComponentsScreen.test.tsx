import "@/test/next-navigation";

import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ComponentsScreen } from "@/features/pipelines/ComponentsScreen";
import { PipelinesScreen } from "@/features/pipelines/PipelinesScreen";
import { ADMIN, renderWithSession, stubFetch } from "@/test/render";

const SOURCE =
  "# Saved comment\ngraphs:\n  convert:\n    - name: result\n      package: builtins\n      method: str\n";
const SAVED = {
  name: "convert.yaml",
  digest: "a".repeat(64),
  reference: ".revisions/library/version.yaml",
  source_text: SOURCE,
  graphs: ["convert"],
  error: null,
};
const VALID = {
  path: "/components/validate",
  method: "POST",
  body: { ok: true, graphs: ["convert"] },
};

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("component authoring", () => {
  it("removes a library only after confirmation and retains a stale-change error", async () => {
    const { calls } = stubFetch([
      { path: "/components", body: [SAVED] },
      {
        path: "/components/source",
        method: "DELETE",
        status: 409,
        body: {
          error: {
            code: "conflict",
            message: "This component changed. Reload it before removing it.",
          },
        },
      },
    ]);
    renderWithSession(<ComponentsScreen />, { user: ADMIN });
    await userEvent.click(await screen.findByRole("button", { name: "Remove convert.yaml" }));
    expect(calls.some((call) => call.init.method === "DELETE")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "Remove component library" }));
    expect(
      await screen.findByText("This component changed. Reload it before removing it."),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(calls.find((call) => call.init.method === "DELETE")?.url).toContain(
      `expected_digest=${SAVED.digest}`,
    );
  });

  it("archives a pipeline without opening its revision page", async () => {
    const pipeline = {
      id: "p1",
      title: "Example",
      slug: "example",
      status: "active",
      created_at: "2026-01-01T00:00:00Z",
    };
    const { calls } = stubFetch([
      { path: "/pipelines", body: { items: [pipeline] } },
      {
        path: "/pipelines/p1/archive",
        method: "POST",
        body: { ...pipeline, status: "archived" },
      },
    ]);
    renderWithSession(<PipelinesScreen />, { user: ADMIN });
    await userEvent.click(await screen.findByRole("button", { name: "Archive" }));
    expect(screen.getByRole("dialog", { name: "Archive this pipeline?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Archive pipeline" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(
      calls.some(
        (call) => call.url.endsWith("/pipelines/p1/archive") && call.init.method === "POST",
      ),
    ).toBe(true);
  });
  it("separates components and pipelines on the same page", async () => {
    stubFetch([
      { path: "/components", body: [] },
      { path: "/pipelines", body: { items: [] } },
    ]);
    renderWithSession(<PipelinesScreen />, { user: ADMIN });
    expect(await screen.findByText("No pipelines yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Components" }));
    expect(await screen.findByText("No components yet.")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Components" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.queryByRole("link", { name: "New revision" })).not.toBeInTheDocument();
  });

  it("requires validation and invalidates it after a source edit", async () => {
    stubFetch([VALID, { path: "/components", body: [] }]);
    renderWithSession(<ComponentsScreen />, { user: ADMIN });
    await userEvent.click(screen.getByRole("button", { name: "New component" }));
    const save = screen.getByRole("button", { name: "Save component revision" });
    expect(save).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Validate component" }));
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.change(screen.getByLabelText("Component document"), {
      target: { value: SOURCE },
    });
    expect(save).toBeDisabled();
  });

  it("saves new source and offers a pipeline using the exact saved reference", async () => {
    const { calls } = stubFetch([
      VALID,
      { path: "/components/revisions", method: "POST", status: 201, body: SAVED },
      { path: "/components/revisions", body: [SAVED] },
      { path: "/components", body: [] },
    ]);
    renderWithSession(<ComponentsScreen />, { user: ADMIN });
    await userEvent.click(screen.getByRole("button", { name: "New component" }));
    fireEvent.change(screen.getByLabelText("Library filename"), {
      target: { value: "convert.yaml" },
    });
    fireEvent.change(screen.getByLabelText("Component document"), {
      target: { value: SOURCE },
    });
    await userEvent.click(screen.getByRole("button", { name: "Validate component" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save component revision" })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save component revision" }));
    expect(await screen.findByText("Component revision saved.")).toBeInTheDocument();
    const link = screen.getByRole("link", { name: "Use convert in a pipeline" });
    expect(link).toHaveAttribute(
      "href",
      `/pipelines/new?library=${encodeURIComponent(SAVED.reference)}&graph=convert`,
    );
    const post = calls.find(
      (call) => call.url.includes("/components/revisions") && call.init.method === "POST",
    );
    expect(JSON.parse(String(post?.init.body))).toEqual({
      name: "convert.yaml",
      source_text: SOURCE,
      expected_digest: null,
    });
  });

  it("loads exact source, sends the original digest, and reports conflicting edits", async () => {
    const { calls } = stubFetch([
      VALID,
      { path: "/components/source", body: SAVED },
      {
        path: "/components/revisions",
        method: "POST",
        status: 409,
        body: {
          error: {
            code: "domain.conflict",
            message: "This component changed. Reload its source before saving again.",
          },
        },
      },
      { path: "/components/revisions", body: [SAVED] },
      { path: "/components", body: [SAVED] },
    ]);
    renderWithSession(<ComponentsScreen />, { user: ADMIN });
    await userEvent.click(
      await screen.findByRole("button", { name: "View/Edit convert.yaml" }),
    );
    expect(await screen.findByLabelText("Component document")).toHaveValue(SOURCE);
    fireEvent.change(screen.getByLabelText("Component document"), {
      target: { value: SOURCE + "# edited" },
    });
    await userEvent.click(screen.getByRole("button", { name: "Validate component" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save component revision" })).toBeEnabled(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save component revision" }));
    expect(await screen.findByText(/This component changed/)).toBeInTheDocument();
    const post = calls.find(
      (call) => call.url.includes("/components/revisions") && call.init.method === "POST",
    );
    expect(JSON.parse(String(post?.init.body)).expected_digest).toBe(SAVED.digest);
    expect(screen.getByLabelText("Component document")).toHaveValue(SOURCE + "# edited");
  });

  it("loads older source without treating it as validated", async () => {
    const old = { ...SAVED, digest: "b".repeat(64), source_text: "# older source\n" };
    stubFetch([
      { path: "/components/source", body: SAVED },
      { path: "/components/revisions", body: [SAVED, old] },
      { path: "/components", body: [SAVED] },
    ]);
    renderWithSession(<ComponentsScreen />, { user: ADMIN });
    await userEvent.click(
      await screen.findByRole("button", { name: "View/Edit convert.yaml" }),
    );
    await screen.findByLabelText("Component document");
    await userEvent.click(screen.getByText("Saved component revisions"));
    await userEvent.click(
      await screen.findByRole("button", { name: "Load source bbbbbbbbbbbb" }),
    );
    expect(screen.getByLabelText("Component document")).toHaveValue(old.source_text);
    expect(screen.getByRole("button", { name: "Save component revision" })).toBeDisabled();
  });
});
