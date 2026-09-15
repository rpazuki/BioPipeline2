#!/usr/bin/env node
/**
 * Fail if `src/generated/api-types.ts` is stale.
 *
 * The backend already gates `contracts/openapi.json` against the running API.
 * That leaves one gap: the contract can be regenerated and committed while the
 * TypeScript built from it is not, and nothing notices until a component reads
 * a field the server stopped sending. This closes it — the same check, one
 * link further down the chain.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const here = fileURLToPath(new URL(".", import.meta.url));
const committed = join(here, "..", "src", "generated", "api-types.ts");
const contract = join(here, "..", "..", "contracts", "openapi.json");

const scratch = mkdtempSync(join(tmpdir(), "bp-generated-"));
const candidate = join(scratch, "api-types.ts");

try {
  execFileSync(
    process.execPath,
    [join(here, "..", "node_modules", "openapi-typescript", "bin", "cli.js"), contract, "-o", candidate],
    { stdio: "pipe" },
  );
  const fresh = readFileSync(candidate, "utf8");
  const existing = readFileSync(committed, "utf8");
  if (fresh !== existing) {
    console.error(
      "src/generated/api-types.ts is stale.\n" +
        "The API contract changed without the client being regenerated, so every\n" +
        "screen typed against it is now wrong. Run:\n" +
        "    npm run generate --prefix frontend",
    );
    process.exit(1);
  }
  console.log("generated: the API client matches the contract");
} finally {
  rmSync(scratch, { recursive: true, force: true });
}
