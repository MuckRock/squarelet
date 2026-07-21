import { test, expect } from "@playwright/test";
import { login } from "./helpers";

// Matches the verification-gated client seeded in seed_e2e_data.py
const CLIENT_ID = "e2e-verify-client";
const REDIRECT_URI = "https://dev.squarelet.com/";
const SCOPE = "openid profile email";

const AUTHORIZE_PATH =
  `/openid/authorize?client_id=${CLIENT_ID}` +
  `&redirect_uri=${encodeURIComponent(REDIRECT_URI)}` +
  `&response_type=code&scope=${encodeURIComponent(SCOPE)}` +
  `&state=e2e-state`;

test.describe("OIDC verification notice", () => {
  test.describe("Unverified user authorizing a gated client", () => {
    test.beforeEach(async ({ page }) => {
      // e2e-regular belongs only to their (unverified) individual org
      await login(page, "e2e-regular");
    });

    test("shows the verification notice instead of proceeding", async ({ page }) => {
      await page.goto(AUTHORIZE_PATH);
      await expect(page.locator("#verification-notice")).toBeVisible();
    });

    test("renders the client's verification notice text", async ({ page }) => {
      await page.goto(AUTHORIZE_PATH);
      await expect(page.locator("#verification-notice")).toContainText(
        "Uploading documents requires a verified newsroom.",
      );
    });

    test("offers an enabled request-verification link (email confirmed)", async ({
      page,
    }) => {
      await page.goto(AUTHORIZE_PATH);
      // e2e-regular has a confirmed email, so verification can be requested.
      // They belong to no newsroom, so the individual verification option shows.
      const link = page
        .locator("#verification-notice .request-verification")
        .first();
      await expect(link).toBeVisible();
      await expect(link).toBeEnabled();
    });

    test("continuing proceeds past the notice to the client", async ({ page }) => {
      await page.goto(AUTHORIZE_PATH);
      await page.locator("#verification-continue").click();
      // lands back on the client redirect_uri (dev home), leaving the authorize flow
      await page.waitForURL((url) => !url.pathname.startsWith("/openid/authorize"));
      await expect(page.locator("#verification-notice")).toHaveCount(0);
    });
  });

  test.describe("Verified user authorizing a gated client", () => {
    test.beforeEach(async ({ page }) => {
      // e2e-member belongs to the verified e2e-public-org
      await login(page, "e2e-member");
    });

    test("skips the notice entirely", async ({ page }) => {
      await page.goto(AUTHORIZE_PATH);
      await expect(page.locator("#verification-notice")).toHaveCount(0);
    });
  });
});
