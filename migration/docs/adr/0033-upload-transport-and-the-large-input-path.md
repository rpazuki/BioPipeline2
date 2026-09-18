# ADR 0033: Upload transport, and where the very large inputs go

Date: 2026-09-18
Status: Accepted
Decision owner: Roozbeh Pazuki
Related gaps: G14, G19, G64

## Context

G14 recorded that the plan's single `POST /files/uploads` was a regression
against a system that already did offset-append resumable uploads, and that no
table in the plan could represent an upload in progress. The schema answered
the second half a long time ago — `uploads` has been there, with a status, a
received-byte count and an expiry — and nothing has ever written to it.

[ADR 0006](0006-load-and-data-size-targets.md) sets the sizes this has to work
at: single inputs **up to tens of gigabytes**, 5-20 users, one Linux VM. Two
different problems hide in that range, and the plan
([05-api-and-contracts.md](../../05-api-and-contracts.md)) says as much: "if the
load numbers show inputs above a few GB, add a direct-to-storage path and treat
HTTP upload as the small-file case".

There is no object storage to be direct about. ADR 0008 chose one VM with a
POSIX volume, and ADR 0013 already exposes institutional shares to it.

## Options

- Option A: HTTP upload only, sized for the largest input. One route for everything; a forty-gigabyte transfer through the API process, which also serves every other request.
- Option B: HTTP upload for the small-file case, shared storage for the large one. Two routes, and the researcher has to know which.
- Option C: Add object storage and presigned direct-to-storage uploads. The route the plan gestures at, and a second storage system to run.

## Decision

**Option B.**

**The direct-to-storage path is the share.** A researcher with a forty-gigabyte
BAM does not want it going through a web page at all; they want `rsync` or
`scp`, which restarts, parallelises, and is what their institution's storage is
built around. The platform's job for that file is to let them *name* it, which
shared-storage roots already do. Sending it through HTTP would be a worse
version of a tool they already have.

**HTTP upload is for the files that have no other route** — a mapping YAML, a
metadata CSV, a plate-reader export a machine wrote to a laptop. Megabytes to a
few gigabytes, and the thing that matters is that it does not have to start
again when the VPN drops.

### The protocol

```text
POST   /api/v1/uploads                      open one; returns the id and the chunk ceiling
PATCH  /api/v1/uploads/{id}                 append at an offset; Content-Range says where
GET    /api/v1/uploads/{id}                 where it got to — the whole of resuming
POST   /api/v1/uploads/{id}/complete        verify, and mint an artifact
DELETE /api/v1/uploads/{id}                 abandon it and release the disk
```

Answering what document 05 asked to have stated:

| Question | Answer |
| --- | --- |
| Maximum chunk | `upload_chunk_max_bytes`, default 64 MB. The browser uses 8 MB regardless, so a failure is cheap and progress moves. |
| Maximum total | `upload_max_total_bytes`, default 500 GB — a ceiling, not a target. A declared size above it is refused before a byte is sent, naming the share as the route instead. |
| Checksum | SHA-256, optional from the client. `crypto.subtle` can only digest a whole buffer, so a browser cannot compute one without reading the file into memory; the server always records the checksum it computed over what arrived. A client that declares one gets the stronger guarantee, and a mismatch ends the upload. |
| Expiry | `upload_expiry_hours`, default 48, **measured from the last chunk**. A transfer slow enough to outlive the window is visibly in progress, and expiring it would be the platform deleting work it can see happening. |
| Unexpected offset | 409 `upload.offset_conflict`, carrying `expected_offset`. Never silently accepted. |

### What holds it together

**The row is the truth; the file is repaired to match it.** The opposite
ordering from artifact promotion — bytes first, row second — and for the
opposite reason. A promoted artifact whose bytes are missing is a lie in the
audit trail; a staging file with bytes nobody recorded is only garbage from a
request that died. So an append fsyncs and then commits, and the next append
truncates the file back to what the row says. A file *shorter* than its row is
the one case where the file wins, because the checksum will be taken over the
file.

**The lock is on the file, not on a row.** Appending is serialised with
`flock`, held for as long as bytes are moving. `SELECT FOR UPDATE` would mean a
database transaction open for the length of a transfer — minutes of
idle-in-transaction per upload, which costs autovacuum and the connection pool
for something that is not a database problem.

**Nothing is ever fully in memory**, at either end. The browser sends `Blob`
slices; the API streams them to disk with a bounded buffer, and enforces the
cap against bytes *received* rather than against `Content-Length`, which is a
claim by the sender.

### From upload to run

A field value of `upload:<id>` is resolved **at submission**, and the run
records what it needs staged. The worker hardlinks the artifact into the run's
workspace at `inputs/<upload id>/<filename>` before any container starts, which
is the path the task spec already names.

Resolving at submission means an upload that expired, or was never finished, is
a message next to the field rather than a container that cannot find its input
an hour later. Staging in the worker means the workspace stays the worker's to
create and destroy, and a run that waits in the queue holds nothing on a host
that may never claim it.

## Consequences

- The `uploads` table finally has a writer, and `ArtifactKind.UPLOAD_INPUT` a producer.
- `artifacts.owner_id` is now read. Artifact visibility was derived entirely from the owning run, so an upload — which has no run — was invisible to the person who uploaded it.
- A researcher whose input is tens of gigabytes is told, in the refusal itself, to put it on a share. That is only a good answer while a share exists, so a deployment with no registered root has a worse story for large files than for small ones.
- `upload_max_total_bytes` at 500 GB is far above what ADR 0006 sizes for. It is deliberately a ceiling against nonsense rather than a policy, and a deployment that wants to push people to the share lowers it.
- The API and the workers must share a filesystem, as they already must for live log tailing. Splitting them breaks staged uploads, which is a Phase 9 question and not a v1 one.
- No `url` source mode. It stays unbuilt (G15), and the SSRF controls document 05 specifies stay unwritten, because nothing yet needs it.

## Follow-up updates required

- `gaps.md`: G14 closes; G19 (range requests) was closed by the download work.
- `14-gap-closure-ledger.md` records what the work opened.
- `05-api-and-contracts.md` carries the answers above rather than the questions.
