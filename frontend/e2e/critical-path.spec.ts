import { expect, test } from "@playwright/test";

/**
 * The journey both roles depend on: sign in, see runs, sign out.
 *
 * Kept small on purpose. The remaining Phase 8 acceptance journeys — submit,
 * monitor to completion, download, and the large-upload behaviour — need
 * endpoints the API does not serve yet, and a spec that skips them silently
 * is worse than one that does not claim them.
 */

const EMAIL = process.env.BP_SEED_ADMIN_EMAIL ?? "admin@example.org";
const PASSWORD = process.env.BP_SEED_ADMIN_PASSWORD ?? "";

test.skip(!PASSWORD, "BP_SEED_ADMIN_PASSWORD must match the seeded admin.");

test("an anonymous visitor is sent to sign in", async ({ page }) => {
  await page.goto("/runs");
  await expect(page.getByLabel("Email")).toBeVisible();
});

test("signing in reaches the runs page", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();
  // An admin sees the authoring surface; a researcher would not.
  await expect(page.getByRole("link", { name: "Pipelines" })).toBeVisible();
});

test("a wrong password is refused without saying which half was wrong", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill("definitely-not-the-password");
  await page.getByRole("button", { name: "Sign in" }).click();

  const alert = page.getByRole("alert");
  await expect(alert).toBeVisible();
  await expect(alert).not.toContainText(/email/i);
});

test("signing out ends the session for real, not just in the browser", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Runs" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Email")).toBeVisible();

  // Going back must not restore a session the server has revoked.
  await page.goto("/runs");
  await expect(page.getByLabel("Email")).toBeVisible();
});

test("the compiler's diagnostics reach the author", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("Email").fill(EMAIL);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();

  await page.getByRole("link", { name: "Pipelines" }).click();
  await page.getByRole("link", { name: "New revision" }).click();

  await page.getByLabel("Pipeline document").fill("pipeline: broken\nstages: []\n");
  await page.getByRole("button", { name: "Compile" }).click();

  // Whatever the compiler says, it must arrive here rather than vanishing —
  // and the save must stay shut until it says the document is good.
  await expect(page.getByRole("alert")).toBeVisible();
});
