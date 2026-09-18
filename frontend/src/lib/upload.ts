/**
 * Sending a file to the platform, one chunk at a time.
 *
 * The transfer a researcher starts before lunch and finds broken when they get
 * back, because a campus VPN does not care what you were doing. So the whole
 * of this module is about the two things that make that survivable.
 *
 * **Nothing is read into memory.** A chunk is a `Blob` slice — a view on the
 * file on disk — handed straight to `fetch`. A forty-gigabyte input never
 * exists in the tab, at any point.
 *
 * **The server owns the offset, not this code.** Every failure is recovered by
 * asking where the upload got to and continuing from there, rather than by
 * trusting a counter kept on this side. That is also what makes a *manual*
 * retry, minutes later and possibly in a new tab, resume rather than restart.
 *
 * No checksum is sent. `crypto.subtle` can only digest a whole buffer, so
 * computing one in the browser would mean reading the entire file into memory
 * — the one thing this module exists to avoid. The server records the checksum
 * it computed over what arrived, which proves the bytes were stored intact but
 * not that they left intact; a client that can afford the read may declare one
 * when it opens the upload.
 */

import { uploads, type Upload } from "@/lib/api";
import type { ApiClient } from "@/lib/client";
import { ApiError } from "@/lib/errors";

/**
 * The largest slice worth sending in one request.
 *
 * The deployment's ceiling can be far higher, and using it would mean a
 * progress bar that moves once and a failure that costs the whole thing.
 */
export const CHUNK_CEILING = 8 * 1024 * 1024;

/** Consecutive failures on one chunk before the transfer gives up. */
const ATTEMPTS = 3;

export interface Progress {
  sent: number;
  total: number;
}

export interface UploadOptions {
  onProgress?: (progress: Progress) => void;
  signal?: AbortSignal;
  /** An upload already opened, to carry on with rather than start again. */
  resume?: Upload;
}

export function chunkSize(client: ApiClient): number {
  return Math.min(client.settings.upload_chunk_max_bytes, CHUNK_CEILING);
}

function offsetFrom(error: unknown): number | null {
  if (!(error instanceof ApiError) || error.code !== "upload.offset_conflict") return null;
  const expected = error.details["expected_offset"];
  return typeof expected === "number" ? expected : null;
}

/**
 * Send a file and return the completed upload.
 *
 * The `reference` on the result is what a form field should hold: it names the
 * upload, and the server turns it into the path a container reads.
 */
export async function uploadFile(
  client: ApiClient,
  file: File,
  options: UploadOptions = {},
): Promise<Upload> {
  const { onProgress, signal } = options;
  let upload =
    options.resume ??
    (await uploads.create(client, { filename: file.name, sizeBytes: file.size }));

  let offset = upload.received_bytes;
  const size = chunkSize(client);
  onProgress?.({ sent: offset, total: file.size });

  let failures = 0;
  while (offset < file.size) {
    signal?.throwIfAborted();
    const slice = file.slice(offset, Math.min(offset + size, file.size));
    try {
      upload = await uploads.append(client, upload.id, slice, {
        offset,
        total: file.size,
        ...(signal ? { signal } : {}),
      });
      offset = upload.received_bytes;
      failures = 0;
    } catch (error) {
      signal?.throwIfAborted();
      const expected = offsetFrom(error);
      if (expected !== null) {
        // Somebody — a retry of ours, another tab, a request that died after
        // writing — moved the upload. The server's number wins, always.
        offset = expected;
        continue;
      }
      if (++failures >= ATTEMPTS || !(error instanceof ApiError) || !error.isTransient) {
        throw error;
      }
      // Ask rather than assume: a dropped connection may have delivered most
      // of the chunk, and resending from where it really got to is the
      // difference between losing eight megabytes and losing four hours.
      upload = await uploads.get(client, upload.id);
      offset = upload.received_bytes;
    }
    onProgress?.({ sent: offset, total: file.size });
  }

  return uploads.complete(client, upload.id);
}
