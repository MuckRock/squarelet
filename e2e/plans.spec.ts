import { test, expect } from "@playwright/test";
import { login, runManageCommand } from "./helpers";

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

test.describe("Plan purchase organization selection", () => {
  // The organization-selection block renders when the user has eligible
  // organizations OR the plan is for groups (so a new org can be created).
  // Otherwise the "no subscription options" message is shown instead.
  const orgForm = "[data-plan-purchase-form]";

  test.describe("Group plan, user with no group orgs", () => {
    // e2e-regular is a member of no organizations, so the org queryset is
    // empty for a groups-only plan. The form must still offer "Create a new
    // organization" rather than the no-options message.
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-regular");
      await page.goto("/plans/e2e-test-plan/");
    });

    test("renders the organization selection block", async ({ page }) => {
      await expect(
        page.locator(`${orgForm} .organization-selection`),
      ).toBeVisible();
    });

    test("offers the create-new-organization option", async ({ page }) => {
      await expect(
        page.locator(`${orgForm} select.org-select option[value="new"]`),
      ).toHaveCount(1);
    });

    test("does not show the no-subscription-options message", async ({ page }) => {
      await expect(
        page.locator(`${orgForm} .no-subscription-options`),
      ).toHaveCount(0);
    });
  });

  test.describe("Group plan, user with no group orgs and unverified email", () => {
    // A user must verify their email before they can create an organization.
    // With no eligible orgs and an unverified email, the create-new option must
    // be withheld and an email-verification message shown instead.
    test.beforeEach(async ({ page }) => {
      runManageCommand(
        `shell -c "from allauth.account.models import EmailAddress; EmailAddress.objects.filter(user__username='e2e-regular').update(verified=False)"`,
      );
      await login(page, "e2e-regular");
      await page.goto("/plans/e2e-test-plan/");
    });

    test.afterEach(() => {
      // Restore the verified email so other tests see the seeded state
      runManageCommand(
        `shell -c "from allauth.account.models import EmailAddress; EmailAddress.objects.filter(user__username='e2e-regular').update(verified=True)"`,
      );
    });

    test("does not offer the create-new-organization option", async ({ page }) => {
      await expect(
        page.locator(`${orgForm} select.org-select option[value="new"]`),
      ).toHaveCount(0);
    });

    test("shows the email-verification message", async ({ page }) => {
      await expect(
        page.locator(`${orgForm} .no-subscription-options.unverified-email`),
      ).toBeVisible();
    });
  });

  test.describe("Individual-only plan", () => {
    // The professional plan is for individuals only. The user's individual
    // organization populates the queryset, so the selection renders without a
    // create-new option and without the no-options message.
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-regular");
      await page.goto("/plans/professional/");
    });

    test("renders the organization selection block", async ({ page }) => {
      await expect(
        page.locator(`${orgForm} .organization-selection`),
      ).toBeVisible();
    });

    test("does not offer the create-new-organization option", async ({ page }) => {
      await expect(
        page.locator(`${orgForm} select.org-select option[value="new"]`),
      ).toHaveCount(0);
    });

    test("does not show the no-subscription-options message", async ({ page }) => {
      await expect(
        page.locator(`${orgForm} .no-subscription-options`),
      ).toHaveCount(0);
    });
  });
});
