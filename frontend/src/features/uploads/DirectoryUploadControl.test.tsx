import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { DirectoryUploadControl } from "./DirectoryUploadControl";
import { uploadFile } from "@/lib/upload";
import { RESEARCHER, renderWithSession, stubFetch } from "@/test/render";
import type { Upload } from "@/lib/api";

vi.mock("@/lib/upload", () => ({ uploadFile: vi.fn() }));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.resetAllMocks();
});
const completed = {
  id: "file-id",
  reference: "upload:file-id",
  status: "completed",
  received_bytes: 1,
} as Upload;

it("uploads folder members and submits their relative paths before using the directory reference", async () => {
  vi.mocked(uploadFile).mockResolvedValue(completed);
  const { calls } = stubFetch([
    {
      path: "/uploads/directories",
      method: "POST",
      body: { ...completed, id: "directory-id", reference: "upload:directory-id" },
    },
  ]);
  const onChange = vi.fn();
  renderWithSession(
    <DirectoryUploadControl
      id="data"
      value=""
      onChange={onChange}
      sources={["folder", "zip", "shared"]}
    />,
    { user: RESEARCHER },
  );
  const file = new File(["content"], "a.txt");
  Object.defineProperty(file, "webkitRelativePath", { value: "experiment/nested/a.txt" });
  await userEvent.upload(screen.getByLabelText("Choose folder"), file);
  await waitFor(() => expect(onChange).toHaveBeenCalledWith("upload:directory-id"));
  const body = JSON.parse(
    String(calls.find((call) => call.url.includes("/uploads/directories"))?.init.body),
  );
  expect(body.name).toBe("experiment");
  expect(body.files).toEqual([{ path: "nested/a.txt", upload_id: "file-id" }]);
  expect(body.request_id).toBeTruthy();
});

it("converts an uploaded ZIP into a directory instead of passing the ZIP to the pipeline", async () => {
  vi.mocked(uploadFile).mockResolvedValue(completed);
  const { calls } = stubFetch([
    {
      path: "/uploads/directories",
      method: "POST",
      body: { ...completed, reference: "upload:expanded-id" },
    },
  ]);
  const onChange = vi.fn();
  renderWithSession(
    <DirectoryUploadControl id="data" value="" onChange={onChange} sources={["zip"]} />,
    { user: RESEARCHER },
  );
  await userEvent.upload(
    screen.getByLabelText("Choose ZIP file"),
    new File(["zip"], "experiment.zip", { type: "application/zip" }),
  );
  await waitFor(() => expect(onChange).toHaveBeenCalledWith("upload:expanded-id"));
  const body = JSON.parse(
    String(calls.find((call) => call.url.includes("/uploads/directories"))?.init.body),
  );
  expect(body.zip_upload_id).toBe("file-id");
  expect(body).not.toHaveProperty("files");
});

it("offers only the shared path when publication policy disallows uploads", () => {
  const onChange = vi.fn();
  renderWithSession(
    <DirectoryUploadControl id="data" value="" onChange={onChange} sources={["shared"]} />,
    { user: RESEARCHER },
  );
  expect(screen.queryByLabelText("Choose folder")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("Choose ZIP file")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("Shared directory path"), {
    target: { value: "/mnt/share/input" },
  });
  expect(onChange).toHaveBeenCalledWith("/mnt/share/input");
});
