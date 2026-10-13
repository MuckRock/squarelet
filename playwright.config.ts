import { defineConfig } from "@playwright/test";
import { execSync } from "child_process";

// The visual spec saves screenshots under the short hash of the code they
// show, and compares against VISUAL_EXPECTED's folder, which defaults to the
// same one. `inv test-visual --baseline` sets both.
process.env.VISUAL_ACTUAL ??= execSync("git rev-parse --short HEAD")
  .toString()
  .trim();
process.env.VISUAL_EXPECTED ??= process.env.VISUAL_ACTUAL;

export default defineConfig({
  testDir: "./e2e",
  workers: 2,
  fullyParallel: false,
  timeout: 30_000,
  expect: {
    timeout: 10_000,
  },
  use: {
    baseURL: "https://dev.squarelet.com",
    ignoreHTTPSErrors: true,
    // Fail a stalled navigation before it can consume the whole test budget.
    navigationTimeout: 20_000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      testIgnore: /visual\.spec\.ts/,
      use: {
        browserName: "chromium",
        viewport: { width: 1280, height: 720 },
      },
    },
    {
      name: "firefox",
      testIgnore: /visual\.spec\.ts/,
      use: {
        browserName: "firefox",
        viewport: { width: 1280, height: 720 },
      },
    },
    {
      name: "webkit",
      testIgnore: /visual\.spec\.ts/,
      use: {
        browserName: "webkit",
        viewport: { width: 1280, height: 720 },
      },
    },
    // The visual projects reseed the same users, so run them with one worker,
    // as `inv test-visual` does.
    {
      name: "visual",
      testMatch: /visual\.spec\.ts/,
      timeout: 60_000,
      use: {
        browserName: "chromium",
        viewport: { width: 1280, height: 720 },
      },
    },
    {
      name: "visual-phone",
      testMatch: /visual\.spec\.ts/,
      timeout: 60_000,
      use: {
        browserName: "chromium",
        viewport: { width: 390, height: 844 },
      },
    },
  ],
  globalSetup: "./e2e/global-setup.ts",
  globalTeardown: "./e2e/global-teardown.ts",
  // Platform-specific and compared only against a baseline recorded on the
  // same machine, so they are not committed.
  snapshotPathTemplate: `{testDir}/__screenshots__/${process.env.VISUAL_EXPECTED}/{projectName}/{arg}{ext}`,
  reporter: [["list"], ["html", { open: "never" }]],
});
