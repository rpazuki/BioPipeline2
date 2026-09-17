import "@/test/next-navigation";

import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ArtifactsPanel } from "@/features/runs/components/ArtifactsPanel";
import { StorageScreen } from "@/features/storage/StorageScreen";
import { ADMIN, renderWithSession, stubFetch, type Route } from "@/test/render";

const RUN_ID = "00000000-0000-4000-8000-0000000000f1";
const FILE_ID = "00000000-0000-4000-8000-0000000000a1";
const TREE_ID = "00000000-0000-4000-8000-0000000000a2";

afterEach(() => vi.unstubAllGlobals());

function root(overrides: Record<string, unknown> = {}) {
  return {
    id: "bio-lab",
    label: "Bio-lab share",
    root_path: "/mnt/nas01/bio-lab",
    readable: true,
    writable: false,
    identity_mode: "service_account",
    attested_by: ADMIN.user_id,
    attested_at: "2026-09-01T09:00:00Z",
    attestation_note: "Checked group bio-lab on nas01.",
    revoked_at: null,
    created_at: "2026-09-01T09:00:00Z",
    visible: true,
    in_use: true,
    ...overrides,
  };
}

describe("shared storage", () => {
  it("says what nothing being registered means", async () => {
    stubFetch([{ path: "/storage/roots", body: { items: [] } }]);
    renderWithSession(<StorageScreen />, { user: ADMIN });
    expect(await screen.findByText("No storage root is registered.")).toBeInTheDocument();
    expect(
      screen.getByText(/nothing that names a file on the lab's own storage/),
    ).toBeVisible();
  });

  it("shows a working root as working", async () => {
    stubFetch([{ path: "/storage/roots", body: { items: [root()] } }]);
    renderWithSession(<StorageScreen />, { user: ADMIN });
    expect(await screen.findByText("in use")).toBeInTheDocument();
    expect(screen.getByText("/mnt/nas01/bio-lab")).toBeInTheDocument();
    // The attestation is the product; it is on the page, not behind a click.
    expect(screen.getByText("Checked group bio-lab on nas01.")).toBeInTheDocument();
  });

  it("says when the share has gone rather than quietly dropping it", async () => {
    // `shared_root_mounts` skips an unreachable root silently, which is right
    // there and invisible everywhere else.
    stubFetch([
      { path: "/storage/roots", body: { items: [root({ visible: false, in_use: false })] } },
    ]);
    renderWithSession(<StorageScreen />, { user: ADMIN });
    expect(await screen.findByText("not there")).toBeInTheDocument();
    expect(screen.getByText(/Submissions naming it will fail/)).toBeInTheDocument();
  });

  it("shows a withdrawn root with a way back", async () => {
    stubFetch([
      {
        path: "/storage/roots",
        body: {
          items: [root({ revoked_at: "2026-09-10T09:00:00Z", readable: false, in_use: false })],
        },
      },
    ]);
    renderWithSession(<StorageScreen />, { user: ADMIN });
    expect(await screen.findByText("withdrawn")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Reinstate" })).toBeInTheDocument();
  });

  it("cannot be registered without an attestation", async () => {
    // There is no version of this form where an empty attestation is a thing
    // somebody meant, so it does not get as far as a request.
    const { calls } = stubFetch([
      { path: "/storage/roots", body: { items: [] } },
      { path: "/storage/roots", method: "POST", status: 201, body: root() },
    ]);
    const user = userEvent.setup();
    renderWithSession(<StorageScreen />, { user: ADMIN });
    await user.click(await screen.findByRole("button", { name: "Register a root" }));

    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Path"), "/mnt/nas01/bio-lab");
    await user.type(within(dialog).getByLabelText("Label"), "Bio-lab share");
    await user.type(within(dialog).getByLabelText("Identifier"), "bio-lab");

    const submit = within(dialog).getByRole("button", { name: "Register" });
    expect(submit).toBeDisabled();
    await user.type(within(dialog).getByLabelText("What you are attesting"), "Checked nas01.");
    expect(submit).toBeEnabled();
    expect(calls.some((call) => (call.init.method ?? "GET") === "POST")).toBe(false);
  });

  it("sends what was typed", async () => {
    const { calls } = stubFetch([
      { path: "/storage/roots", body: { items: [] } },
      { path: "/storage/roots", method: "POST", status: 201, body: root() },
    ]);
    const user = userEvent.setup();
    renderWithSession(<StorageScreen />, { user: ADMIN });
    await user.click(await screen.findByRole("button", { name: "Register a root" }));

    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Path"), "/mnt/nas01/bio-lab");
    await user.type(within(dialog).getByLabelText("Label"), "Bio-lab share");
    await user.type(within(dialog).getByLabelText("Identifier"), "bio-lab");
    await user.type(within(dialog).getByLabelText("What you are attesting"), "Checked nas01.");
    await user.click(within(dialog).getByRole("button", { name: "Register" }));

    await waitFor(() => {
      const post = calls.find((call) => (call.init.method ?? "GET") === "POST");
      expect(JSON.parse(String(post!.init.body))).toMatchObject({
        id: "bio-lab",
        root_path: "/mnt/nas01/bio-lab",
        attestation_note: "Checked nas01.",
        readable: true,
        writable: false,
      });
    });
  });
});

describe("getting a run's outputs", () => {
  const listed = (items: unknown[]): Route => ({
    path: `/runs/${RUN_ID}/artifacts`,
    body: { items },
  });

  const file = {
    id: FILE_ID,
    kind: "task_output",
    filename: "report.txt",
    size_bytes: 1024,
    checksum_sha256: "a".repeat(64),
    created_at: "2026-09-01T09:00:00Z",
    expires_at: null,
    is_directory: false,
  };

  const tree = { ...file, id: TREE_ID, filename: "plate_01", is_directory: true };

  it("offers a file as a link the browser streams", async () => {
    // Never a fetch: an artifact can be tens of gigabytes, and a blob URL
    // would hold all of it in the tab before a byte reached the disk.
    stubFetch([listed([file])]);
    renderWithSession(<ArtifactsPanel runId={RUN_ID} live={false} />, { user: ADMIN });
    const link = await screen.findByRole("link", { name: "Download" });
    expect(link).toHaveAttribute(
      "href",
      expect.stringContaining(`/artifacts/${FILE_ID}/download`),
    );
    expect(link).toHaveAttribute("download", "report.txt");
  });

  it("offers a directory as its files, one link each", async () => {
    stubFetch([
      listed([tree]),
      {
        path: `/artifacts/${TREE_ID}`,
        body: {
          ...tree,
          available: true,
          files: [
            { path: "growth.csv", size_bytes: 40, checksum_sha256: "b".repeat(64) },
            { path: "fit/params.json", size_bytes: 12, checksum_sha256: "c".repeat(64) },
          ],
        },
      },
    ]);
    const user = userEvent.setup();
    renderWithSession(<ArtifactsPanel runId={RUN_ID} live={false} />, { user: ADMIN });

    await user.click(await screen.findByRole("button", { name: "Files" }));
    const nested = await screen.findByRole("link", { name: "fit/params.json" });
    expect(nested).toHaveAttribute(
      "href",
      expect.stringContaining(`/artifacts/${TREE_ID}/files/fit/params.json`),
    );
    expect(screen.getByRole("link", { name: "growth.csv" })).toBeInTheDocument();
    // No whole-tree download: packaging a multi-gigabyte output on a click is
    // not something the API process should do.
    expect(screen.queryByRole("link", { name: "Download" })).not.toBeInTheDocument();
  });

  it("says when an output has expired rather than offering a dead link", async () => {
    stubFetch([
      listed([tree]),
      {
        path: `/artifacts/${TREE_ID}`,
        body: {
          ...tree,
          available: false,
          unavailable_reason: "These outputs have been removed.",
          files: [],
        },
      },
    ]);
    const user = userEvent.setup();
    renderWithSession(<ArtifactsPanel runId={RUN_ID} live={false} />, { user: ADMIN });
    await user.click(await screen.findByRole("button", { name: "Files" }));
    expect(await screen.findByText("These outputs have been removed.")).toBeInTheDocument();
  });
});
