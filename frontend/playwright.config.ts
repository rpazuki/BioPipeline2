import { defineConfig, devices } from "@playwright/test";

/**
 * End-to-end tests run against a **real** backend, not a mock.
 *
 * That is the point of them: the component tests already prove the screens
 * behave, with `fetch` stubbed. What they cannot prove is that the cookie is
 * accepted, the CSRF header is the one the server wants, the path prefix is
 * respected, and the error envelope is shaped as the client assumes. Every one
 * of those is a contract between two processes.
 *
 * Prerequisites, deliberately not automated away — starting a database and
 * migrating it from a test runner hides which of them broke:
 *
 *     make db-up && make migrate
 *     BP_SEED_ADMIN_PASSWORD=... make seed
 *     make api            # in another terminal
 *
 * Then, from `frontend/`:
 *
 *     BP_SEED_ADMIN_PASSWORD=... npm run e2e
 */
const API = process.env.E2E_API_ORIGIN ?? "http://localhost:8000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    reuseExistingServer: !process.env.CI,
    env: { NEXT_PUBLIC_API_ORIGIN: API },
    timeout: 120_000,
  },
});
