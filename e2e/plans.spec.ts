import { test, expect } from "@playwright/test";
import { login } from "./helpers";

test.describe("Plan purchase redirects", () => {
  test("purchase_redirect query param is preserved in hidden form input", async ({ page }) => {
    await login(page, "e2e-admin");
    await page.goto("/plans/e2e-test-plan/?purchase_redirect=https://example.com/callback");
    // After redirect to canonical URL, verify the hidden input exists with the correct value
    const hiddenInput = page.locator("input[name='purchase_redirect']");
    await expect(hiddenInput).toHaveValue("https://example.com/callback");
  });

  test("plan redirect view preserves purchase_redirect query param", async ({ page }) => {
    await login(page, "e2e-admin");
    // Navigate to slug-only URL with purchase_redirect
    await page.goto("/plans/e2e-test-plan/?purchase_redirect=https://example.com/callback");
    // After redirect, URL should still contain purchase_redirect
    expect(page.url()).toContain("purchase_redirect=https");
  });
});
