import { test, expect } from "@playwright/test";
import { login, expectFlashMessage } from "./helpers";

test.describe("Organization Viewing", () => {
  test.describe("Anonymous user", () => {
    test("can view public org profile", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("#profile h3")).toContainText("e2e-public-org");
    });

    test("sees admin names in members list", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("#members .user-list")).toBeVisible();
      await expect(page.locator("#members .user-list .user")).toHaveCount(1); // only admins
    });

    test("sees verification badge", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("#verification .status.verified")).toBeVisible();
    });

    test("does NOT see user emails", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator(".user .info .caption")).toHaveCount(0);
    });

    test("does NOT see plan section", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("section#plan")).toHaveCount(0);
    });

    test("cannot access private org (404)", async ({ page }) => {
      const response = await page.goto("/organizations/e2e-private-org/");
      expect(response?.status()).toBe(404);
    });
  });

  test.describe("Signed-in, non-member", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-regular");
    });

    test("sees admin emails", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator(".user .info .caption").first()).toBeVisible();
    });

    test('sees "Request to join" button', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("#join-org-button")).toBeVisible();
    });

    test("does NOT see plan section", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("section#plan")).toHaveCount(0);
    });

    test('members section header says "Admins" not "Members"', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      const header = page.locator("#members > header h2").first();
      await expect(header).toContainText("Admin");
      await expect(header).not.toContainText("Member");
    });

    test("cannot access private org (404)", async ({ page }) => {
      const response = await page.goto("/organizations/e2e-private-org/");
      expect(response?.status()).toBe(404);
    });
  });

  test.describe("Org member", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-member");
    });

    test("sees plan section", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("section#plan")).toBeVisible();
    });

    test('members section header says "Members"', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      const header = page.locator("#members header h2");
      await expect(header).toContainText("Member");
    });

    test("sees all members in user list (not just admins)", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      // Should see both the admin and the member
      await expect(page.locator("#members .user-list .user")).toHaveCount(2);
    });

    test('sees "Leave org" button', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator('button[value="leave"]')).toBeVisible();
    });

    test('does NOT see "Edit profile" link', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("text=Edit profile")).toHaveCount(0);
    });

    test('does NOT see "Manage members" link', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("text=Manage members")).toHaveCount(0);
    });
  });

  test.describe("Org admin", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-admin");
    });

    test('sees "Edit profile" link', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("a:has-text('Edit profile')")).toBeVisible();
    });

    test('sees "Invite members" and "Manage members" links', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("a:has-text('Invite members')")).toBeVisible();
      await expect(page.locator("a:has-text('Manage members')")).toBeVisible();
    });

    test("sees plan section", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("section#plan")).toBeVisible();
    });
  });

  test.describe("MuckRock staff", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-staff");
    });

    test('sees staff toolbar with "View in Django admin"', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator(".staff-toolbar")).toBeVisible();
      await expect(
        page.locator(".staff-toolbar a:has-text('View in Django admin')"),
      ).toBeVisible();
    });

    test('sees "Edit profile" link', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("a:has-text('Edit profile')")).toBeVisible();
    });

    test('sees "Manage members" link', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("a:has-text('Manage members')")).toBeVisible();
    });

    test("sees plan section", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("section#plan")).toBeVisible();
    });

    test("CAN access private org", async ({ page }) => {
      const response = await page.goto("/organizations/e2e-private-org/");
      expect(response?.status()).toBe(200);
      await expect(page.locator("#profile h3")).toContainText("e2e-private-org");
    });
  });
});

test.describe("Profile Editing", () => {
  test("admin can edit unprotected fields", async ({ page }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/update/");

    const aboutField = page.locator("section#details textarea[name='about']");
    await aboutField.fill("Updated by e2e test");
    await page.locator("section#details button[type='submit']").click();

    // Verify change reflected on detail page
    await page.goto("/organizations/e2e-public-org/");
    await expect(page.locator("p.org-about")).toContainText("Updated by e2e test");

    // Clean up: clear the about field
    await page.goto("/organizations/e2e-public-org/update/");
    await page.locator("section#details textarea[name='about']").fill("");
    await page.locator("section#details button[type='submit']").click();
  });

  test("toggling private hides org from anonymous users", async ({ page, browser }) => {
    // Login as admin and make org private
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/update/");

    const privateCheckbox = page.locator("section#details input[name='private']");
    await privateCheckbox.check();
    await page.locator("section#details button[type='submit']").click();

    // Verify anonymous user gets 404
    const anonContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const anonPage = await anonContext.newPage();
    const response = await anonPage.goto(
      "https://dev.squarelet.com/organizations/e2e-public-org/",
    );
    expect(response?.status()).toBe(404);
    await anonContext.close();

    // Undo: uncheck private
    await page.goto("/organizations/e2e-public-org/update/");
    await page.locator("section#details input[name='private']").uncheck();
    await page.locator("section#details button[type='submit']").click();

    // Verify anonymous user can access again
    const anonContext2 = await browser.newContext({ ignoreHTTPSErrors: true });
    const anonPage2 = await anonContext2.newPage();
    const response2 = await anonPage2.goto(
      "https://dev.squarelet.com/organizations/e2e-public-org/",
    );
    expect(response2?.status()).toBe(200);
    await anonContext2.close();
  });

  test("admin can only request changes to protected fields", async ({ page }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/update/");

    // Use city field (safe — doesn't affect the org slug/URL)
    const cityField = page.locator("section#protected input[name='city']");
    await cityField.fill("E2E Test City");

    const explanationField = page.locator(
      "section#protected textarea[name='explanation']",
    );
    await explanationField.fill("E2E test: requesting city change");

    await page.locator("section#protected button[type='submit']").click();

    await expectFlashMessage(page, "submitted and will be reviewed");
  });

  test("staff can accept a change request", async ({ page }) => {
    // First create a change request as admin
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/update/");

    await page.locator("section#protected input[name='city']").fill("Accepted City");
    await page
      .locator("section#protected textarea[name='explanation']")
      .fill("E2E test: to be accepted");
    await page.locator("section#protected button[type='submit']").click();
    await expectFlashMessage(page, "submitted and will be reviewed");

    // Login as staff and review
    await login(page, "e2e-staff");
    await page.goto("/organizations/e2e-public-org/update/");

    await expect(page.locator("#pending-requests")).toBeVisible();
    await page.locator('#pending-requests button[value="accept"]').first().click();

    await expectFlashMessage(page, "accepted and applied");
  });

  test("staff can reject a change request", async ({ page }) => {
    // Create a change request as admin
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/update/");

    await page.locator("section#protected input[name='city']").fill("Rejected City");
    await page
      .locator("section#protected textarea[name='explanation']")
      .fill("E2E test: to be rejected");
    await page.locator("section#protected button[type='submit']").click();
    await expectFlashMessage(page, "submitted and will be reviewed");

    // Login as staff and reject
    await login(page, "e2e-staff");
    await page.goto("/organizations/e2e-public-org/update/");

    await expect(page.locator("#pending-requests")).toBeVisible();
    await page.locator('#pending-requests button[value="reject"]').first().click();

    await expectFlashMessage(page, "rejected");
  });
});

test.describe("Member Management", () => {
  test("admin can invite, resend, and revoke an email invitation", async ({ page }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");

    // Send email invitation
    await page.locator("input[name='emails']").fill("e2e-invited@example.com");
    await page.locator('button[value="addmember"]').click();
    await expectFlashMessage(page, "invitation");

    // Verify pending invitation appears
    await page.goto("/organizations/e2e-public-org/manage-members/");
    await expect(page.locator("section#pending")).toBeVisible();

    // Resend invitation
    await page.locator('button[value="resendinvite"]').first().click();
    await expectFlashMessage(page, "resent");

    // Revoke invitation
    await page.goto("/organizations/e2e-public-org/manage-members/");
    await page.locator('button[value="revokeinvite"]').first().click();
    await expectFlashMessage(page, "revoked");
  });

  test("admin can generate an invite link visible to anonymous users", async ({
    page,
    browser,
  }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");

    // Generate invite link
    await page.locator('button[value="addmember_link"]').click();
    const flashMessage = page.locator("._cls-alerts ._cls-middleAlign", {
      hasText: "Invitation link",
    });
    await expect(flashMessage).toBeVisible({ timeout: 10_000 });

    // Extract the invitation URL from the flash message
    const messageHtml = await flashMessage.innerHTML();
    const urlMatch = messageHtml.match(/\/organizations\/[a-f0-9-]+\/invitation\//);
    expect(urlMatch).toBeTruthy();
    const invitationPath = urlMatch![0];

    // Open URL in anonymous context — should show Sign Up / Log In
    const anonContext = await browser.newContext({ ignoreHTTPSErrors: true });
    const anonPage = await anonContext.newPage();
    await anonPage.goto(`https://dev.squarelet.com${invitationPath}`);
    await expect(anonPage.locator("form a:has-text('Sign Up')")).toBeVisible();
    await expect(anonPage.locator("form a:has-text('Log In')")).toBeVisible();
    await anonContext.close();

    // Verify the link invitation shows "Copy link" (not "Resend") on manage-members
    await page.goto("/organizations/e2e-public-org/manage-members/");
    await expect(page.locator("section#pending")).toBeVisible();
    await expect(page.locator("section#pending button[data-clipboard]")).toBeVisible();

    // Clean up: revoke the link invitation
    await page.locator('section#pending button[value="revokeinvite"]').first().click();
  });

  test("user can request to join and admin can accept", async ({ page }) => {
    // Login as requester and submit join request
    await login(page, "e2e-requester");
    await page.goto("/organizations/e2e-public-org/");
    await page.locator("#join-org-button").click();

    // Wait for modal to appear
    const modal = page.locator("#join-request-modal-backdrop");
    await expect(modal).not.toHaveClass(/_cls-hide/);

    // Click the submit button inside the modal
    await modal.locator('button[name="action"][value="join"]').click();
    await expectFlashMessage(page, "Request to join");

    // Login as admin, navigate to manage-members
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");

    // Verify pending request exists
    await expect(page.locator("section#requests")).toBeVisible();

    // Accept the request
    await page.locator('button[value="acceptinvite"]').first().click();
    await expectFlashMessage(page, "accepted");

    // Clean up: remove the requester from the org
    await page.goto("/organizations/e2e-public-org/manage-members/");
    // Find the membership row for e2e-requester and remove them
    const requesterRow = page.locator(".membership", {
      has: page.locator("h3", { hasText: "e2e-requester" }),
    });
    await requesterRow.locator('button[value="removeuser"]').click();
  });

  test("admin can reject a join request", async ({ page }) => {
    // Login as requester and submit join request
    await login(page, "e2e-requester");
    await page.goto("/organizations/e2e-public-org/");
    await page.locator("#join-org-button").click();

    const modal = page.locator("#join-request-modal-backdrop");
    await expect(modal).not.toHaveClass(/_cls-hide/);
    await modal.locator('button[name="action"][value="join"]').click();
    await expectFlashMessage(page, "Request to join");

    // Login as admin, reject the request
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");
    await expect(page.locator("section#requests")).toBeVisible();
    await page.locator('button[value="rejectinvite"]').first().click();
    await expectFlashMessage(page, "rejected");
  });
});
