import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    // Threads rather than forked processes: a jsdom environment costs about
    // three seconds to spawn per file as a fork, which on a loaded machine is
    // most of a five-second timeout before a test has run a line. These tests
    // need isolation from each other's globals, not from each other's address
    // space.
    pool: "threads",
    // Generous on purpose. A gate that fails because the machine was busy
    // teaches people to re-run it rather than to read it, and a suite nobody
    // believes is worse than no suite.
    testTimeout: 20_000,
    hookTimeout: 20_000,
  },
});
