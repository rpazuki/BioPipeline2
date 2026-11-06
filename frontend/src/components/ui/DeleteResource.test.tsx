import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { DeleteResource } from "./DeleteResource";
import { ADMIN, RESEARCHER, renderWithSession, stubFetch } from "@/test/render";

afterEach(() => vi.unstubAllGlobals());

it("requires confirmation before requesting file deletion", async () => {
  const { calls } = stubFetch([
    { path: "/runs/example", method: "DELETE", status: 202, body: { status: "pending" } },
  ]);
  const done = vi.fn();
  renderWithSession(
    <DeleteResource
      endpoint="/runs/example"
      name="this run"
      description="Delete its server files."
      onDeleted={done}
    />,
    { user: ADMIN },
  );
  await userEvent.click(screen.getByRole("button", { name: "Delete this run" }));
  expect(screen.getByRole("dialog")).toHaveTextContent("Delete its server files.");
  expect(calls).toHaveLength(0);
  await userEvent.click(screen.getByRole("button", { name: "Confirm deletion" }));
  await waitFor(() => expect(done).toHaveBeenCalledOnce());
  expect(calls[0]!.init.method).toBe("DELETE");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("does not expose deletion to researchers", () => {
  const { calls } = stubFetch([]);
  renderWithSession(
    <DeleteResource endpoint="/runs/example" name="this run" description="Delete files." />,
    { user: RESEARCHER },
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  expect(calls).toHaveLength(0);
});

it("keeps the confirmation and error visible when deletion is refused", async () => {
  stubFetch([
    {
      path: "/runs/example",
      method: "DELETE",
      status: 409,
      body: {
        error: { code: "domain.conflict", message: "Wait for the run to stop.", details: {} },
      },
    },
  ]);
  renderWithSession(
    <DeleteResource endpoint="/runs/example" name="this run" description="Delete files." />,
    { user: ADMIN },
  );
  await userEvent.click(screen.getByRole("button", { name: "Delete this run" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm deletion" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Wait for the run to stop.");
  expect(screen.getByRole("dialog")).toBeInTheDocument();
});
