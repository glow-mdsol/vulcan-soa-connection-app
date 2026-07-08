import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

const STORAGE_STATE_PATH = path.join(
  path.dirname(fileURLToPath(import.meta.url)), ".auth", "session.json",
);
const hasBootstrappedSession = fs.existsSync(STORAGE_STATE_PATH);
const frontendPort = Number(process.env.FRONTEND_PORT) || 5173;

test("standalone launch redirects to the configured Aidbox authorize endpoint", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("link", { name: "start a standalone launch" }).click();
  // Aidbox 302s straight to /auth/login for a session-less browser, so the
  // /auth/authorize URL never commits — accept either as proof of the chain.
  await page.waitForURL(/\/auth\/(authorize|login)\?/);
  expect(page.url()).toContain("response_type=code");
});

test.describe("authenticated golden path", () => {
  test.skip(
    !hasBootstrappedSession,
    "requires a one-time manual login bootstrap: " +
      `npx playwright codegen --save-storage=e2e/.auth/session.json http://localhost:${frontendPort} ` +
      "(complete the standalone launch + Aidbox login once, then close the browser)",
  );
  test.use({ storageState: STORAGE_STATE_PATH });

  test("worklist to enroll through the CPG gates to ambiguous decision prompt", async ({ page }) => {
    await page.goto("/");
    await page.getByRole("link", { name: "Use Case 1 Demo Study (Exit Example)" }).click();

    await page.getByLabel("Patient").selectOption("uc1-demo-patient");
    await page.getByRole("button", { name: "Enroll" }).click();

    await expect(page.getByText("0700e721-1f12-4998-89b8-6f4e649b62f7")).toBeVisible();

    const gates = [
      "Accept proposal",
      "Authorize",
      "Schedule",
      "Patient accepts",
      "Site confirms",
      "Perform visit",
    ];
    for (const gate of gates) {
      await page.getByRole("button", { name: gate, exact: true }).click();
    }
    await page.getByRole("button", { name: "Complete visit" }).click();

    await expect(page.getByText("a1806239-54f3-4762-af3f-edb9d80d29dc")).toBeVisible();

    for (const gate of gates) {
      await page.getByRole("button", { name: gate, exact: true }).click();
    }
    await page.getByRole("button", { name: "Withdraw subject" }).click();
    await expect(page.getByText("Subject withdrawn from study.")).toBeVisible();

    await page.getByRole("button", { name: "Complete visit" }).click();
    await expect(page.getByText("Decision needed")).toBeVisible();
    await expect(page.getByRole("button", { name: "Day 7" })).toBeVisible();
    await expect(page.getByRole("button", { name: "End of Study" })).toBeVisible();
  });
});
