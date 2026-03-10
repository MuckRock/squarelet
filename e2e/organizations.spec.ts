import { test, expect } from "@playwright/test";
import { login, deleteTestOrg, expectFlashMessage, resetOrgProfileState, runManageCommand } from "./helpers";

const NEW_ORG_SLUG = "e2e-new-org";

test.describe("Organization Creation", () => {
  test.afterAll(() => {
    deleteTestOrg(NEW_ORG_SLUG);
  });

  test.describe("Authenticated user", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-regular");
    });

    test("creates org with unique name and redirects to org page", async ({ page }) => {
      await page.goto("/organizations/~create");
      await page.locator("input[name='name']").fill("e2e-new-org");
      await page.locator("button[type='submit']").click();
      await expect(page).toHaveURL(/\/organizations\/e2e-new-org\//);
    });

    test("similar name shows matching orgs, force-create works", async ({ page }) => {
      await page.goto("/organizations/~create");
      await page.locator("input[name='name']").fill("e2e public org");
      await page.locator("button[type='submit']").click();

      // Should show matching organizations and a force-create form
      await expect(page).toHaveURL(/\/organizations\/~create/);
      await expect(page.locator("input[name='force'][value='true']")).toBeAttached();

      // The force form reuses the #login_form id with the hidden force field
      await page.locator("#login_form button[type='submit']").click();
      await page.waitForURL((url) => !url.pathname.includes("~create"));
      await expect(page).toHaveURL(/\/organizations\//);
    });
  });

  test.describe("Unauthenticated user", () => {
    test("redirected to login", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/organizations/~create");
      await expect(page).toHaveURL(/\/accounts\/login\//);
    });
  });
});


test.describe("Organization Viewing", () => {
  test.describe("Anonymous user", () => {
    test("can view public org profile", async ({ page }) => {
      const response = await page.goto("/organizations/e2e-public-org/");
      expect(response?.status()).toBe(200);
      await expect(page.locator("#profile h3")).toContainText("e2e-public-org");
    });

    test("cannot access private org (404)", async ({ page }) => {
      const response = await page.goto("/organizations/e2e-private-org/");
      expect(response?.status()).toBe(404);
    });

    test("sees only admins in member list", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("#members .user-list")).toBeVisible();
      await expect(page.locator("#members .user-list .user")).toHaveCount(1); // only admins
    });

    test("sees org verification status", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(
        page.locator("#verification .status.verified"),
      ).toBeVisible();
    });

    test("does NOT see any admin emails", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator(".user .info .caption")).toHaveCount(0);
    });

    test("does NOT see plan section", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("section#plan")).toHaveCount(0);
    });
  });

  test.describe("Signed-in, non-member", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-regular");
    });

    test("cannot access private org (404)", async ({ page }) => {
      const response = await page.goto("/organizations/e2e-private-org/");
      expect(response?.status()).toBe(404);
    });

    test('sees "Request to join" button', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("#join-org-button")).toBeVisible();
    });

    test("does NOT see plan section", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("section#plan")).toHaveCount(0);
    });

    test("sees only admins in member list", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("#members .user-list")).toBeVisible();
      await expect(page.locator("#members .user-list .user")).toHaveCount(1); // only admins
    });

    test("sees admin emails", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator(".user .info .caption").first()).toBeVisible();
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

    test("sees all members in user list (not just admins)", async ({
      page,
    }) => {
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
      await expect(
        page.locator('a[href*="/organizations/e2e-public-org/update/"]'),
      ).toHaveCount(0);
    });

    test('does NOT see "Manage members" link', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(
        page.locator(
          'a[href*="/organizations/e2e-public-org/manage-members/"]',
        ),
      ).toHaveCount(0);
    });
  });

  test.describe("Org admin", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-admin");
    });

    test('sees "Edit profile" link', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(
        page.locator('a[href*="/organizations/e2e-public-org/update/"]'),
      ).toBeVisible();
    });

    test('sees "Invite members" and "Manage members" links', async ({
      page,
    }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(
        page.locator(
          'a[href$="/organizations/e2e-public-org/manage-members/#invite"]',
        ),
      ).toBeVisible();
      await expect(
        page.locator(
          'a[href$="/organizations/e2e-public-org/manage-members/"]',
        ),
      ).toBeVisible();
    });

    test("sees plan section", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("section#plan")).toBeVisible();
    });

    test("sees button to change plans", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(
        page.locator('a[href$="/organizations/e2e-public-org/payment/"]'),
      ).toBeVisible();
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
        page.locator(
          '.staff-toolbar a[href*="/admin/organizations/organization/"]',
        ),
      ).toBeVisible();
    });

    test('sees "Edit profile" link', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(
        page.locator('a[href*="/organizations/e2e-public-org/update/"]'),
      ).toBeVisible();
    });

    test('sees "Manage members" links', async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(
        page.locator(
          'a[href$="/organizations/e2e-public-org/manage-members/#invite"]',
        ),
      ).toBeVisible();
      await expect(
        page.locator(
          'a[href$="/organizations/e2e-public-org/manage-members/"]',
        ),
      ).toBeVisible();
    });

    test("sees plan section", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(page.locator("section#plan")).toBeVisible();
    });

    test("sees button to change plans", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(
        page.locator('a[href$="/organizations/e2e-public-org/payment/"]'),
      ).toBeVisible();
    });

    test("CAN access private org", async ({ page }) => {
      const response = await page.goto("/organizations/e2e-private-org/");
      expect(response?.status()).toBe(200);
      await expect(page.locator("#profile h3")).toContainText(
        "e2e-private-org",
      );
    });
  });
});

test.describe("Profile Editing", () => {
  test.beforeEach(() => {
    resetOrgProfileState("e2e-public-org");
  });

  test("admin can edit unprotected fields", async ({ page }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/update/");

    const aboutField = page.locator("section#details textarea[name='about']");
    await aboutField.fill("Updated by e2e test");
    await page.locator("section#details button[type='submit']").click();

    // Verify change reflected on detail page
    await page.goto("/organizations/e2e-public-org/");
    await expect(page.locator("p.org-about")).toContainText(
      "Updated by e2e test",
    );

    // Clean up: clear the about field
    await page.goto("/organizations/e2e-public-org/update/");
    await page.locator("section#details textarea[name='about']").fill("");
    await page.locator("section#details button[type='submit']").click();
  });

  test("toggling private hides org from anonymous users", async ({
    page,
    browser,
  }) => {
    // Login as admin and make org private
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/update/");

    const privateCheckbox = page.locator(
      "section#details input[name='private']",
    );
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

  test("admin can only request changes to protected fields", async ({
    page,
  }) => {
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

    await expectFlashMessage(page, "success");
  });

  test("staff can accept a change request", async ({ page }) => {
    // First create a change request as admin
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/update/");

    await page
      .locator("section#protected input[name='city']")
      .fill("Accepted City");
    await page
      .locator("section#protected textarea[name='explanation']")
      .fill("E2E test: to be accepted");
    await page.locator("section#protected button[type='submit']").click();
    await expectFlashMessage(page, "success");

    // Login as staff and review
    await login(page, "e2e-staff");
    await page.goto("/organizations/e2e-public-org/update/");

    await expect(page.locator("#pending-requests")).toBeVisible();
    await page
      .locator("#pending-requests input[name='internal_note']")
      .first()
      .fill("E2E staff acceptance note");
    await page
      .locator('#pending-requests button[value="accept"]')
      .first()
      .click();

    await expectFlashMessage(page, "success");
  });

  test("staff can reject a change request", async ({ page }) => {
    // Create a change request as admin
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/update/");

    await page
      .locator("section#protected input[name='city']")
      .fill("Rejected City");
    await page
      .locator("section#protected textarea[name='explanation']")
      .fill("E2E test: to be rejected");
    await page.locator("section#protected button[type='submit']").click();
    await expectFlashMessage(page, "success");

    // Login as staff and reject
    await login(page, "e2e-staff");
    await page.goto("/organizations/e2e-public-org/update/");

    await expect(page.locator("#pending-requests")).toBeVisible();
    await page
      .locator("#pending-requests input[name='internal_note']").first()
      .fill("E2E staff rejection note");
    await page
      .locator('#pending-requests button[value="reject"]')
      .first()
      .click();

    await expectFlashMessage(page, "success");
  });
});

test.describe("Member Management", () => {
  test("admin can invite, resend, and revoke an email invitation", async ({
    page,
  }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");

    // Send email invitation
    await page.locator("input[name='emails']").fill("e2e-invited@example.com");
    await page.locator('button[value="addmember"]').click();
    await expectFlashMessage(page, "success");

    // Verify pending invitation appears
    await page.goto("/organizations/e2e-public-org/manage-members/");
    await expect(page.locator("section#pending")).toBeVisible();

    // Resend invitation
    await page.locator('button[value="resendinvite"]').first().click();
    await expectFlashMessage(page, "success");

    // Revoke invitation
    await page.goto("/organizations/e2e-public-org/manage-members/");
    await page.locator('button[value="revokeinvite"]').first().click();
    await expectFlashMessage(page, "success");
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
    const urlMatch = messageHtml.match(
      /\/organizations\/[a-f0-9-]+\/invitation\//,
    );
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
    await expect(
      page.locator("section#pending button[data-clipboard]"),
    ).toBeVisible();

    // Clean up: revoke the link invitation
    await page
      .locator('section#pending button[value="revokeinvite"]')
      .first()
      .click();
  });

  test("inviting an existing member shows info, not success", async ({
    page,
  }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");

    // e2e-member is already a member per the seed data
    await page.locator("input[name='emails']").fill("e2e-member@example.com");
    await page.locator('button[value="addmember"]').click();

    // Should see an info message, not a "0 invitations sent" success message
    await expectFlashMessage(page, "info");
    const successAlerts = page.locator("._cls-alerts .alert-success");
    await expect(successAlerts).toHaveCount(0);
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
    await expectFlashMessage(page, "success");

    // Login as admin, navigate to manage-members
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");

    // Verify pending request exists
    await expect(page.locator("section#requests")).toBeVisible();

    // Accept the request
    await page.locator('button[value="acceptinvite"]').first().click();
    await expectFlashMessage(page, "success");

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
    await expectFlashMessage(page, "success");

    // Login as admin, reject the request
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");
    await expect(page.locator("section#requests")).toBeVisible();
    await page.locator('button[value="rejectinvite"]').first().click();
    await expectFlashMessage(page, "success");
  });

  test("member role assigned after acceptance", async ({
    page,
  }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");

    // Defensive cleanup: revoke any stale pending invitations
    while (await page.locator('button[value="revokeinvite"]').count()) {
      await page.locator('button[value="revokeinvite"]').first().click();
      await page.goto("/organizations/e2e-public-org/manage-members/");
    }

    // Send invitation with Member role (default)
    await page
      .locator("input[name='emails']")
      .fill("e2e-requester@example.com");
    await page.locator("select[name='role']").selectOption("0");
    await page.locator('button[value="addmember"]').click();
    await expectFlashMessage(page, "success");

    // Verify pending invitation does NOT show Admin badge
    await page.goto("/organizations/e2e-public-org/manage-members/");
    const pendingSection = page.locator("section#pending");
    await expect(pendingSection).toBeVisible();
    const pendingInvitation = pendingSection.locator(".invitation").first();
    await expect(pendingInvitation.locator(".orange.badge")).toHaveCount(0);

    // Login as the invited user and accept from their account page
    await login(page, "e2e-requester");
    await page.goto("/users/e2e-requester/");
    const invitation = page.locator(".invite", {
      has: page.locator("text=e2e-public-org"),
    });
    await invitation.locator('button[value="accept"]').click();
    await expectFlashMessage(page, "success");

    // Verify the user is a member (not admin) in the members list
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");
    const requesterMembership = page.locator(".membership", {
      has: page.locator("h3", { hasText: "e2e-requester" }),
    });
    await expect(requesterMembership).toBeVisible();
    await expect(
      requesterMembership.locator('button[value="makeadmin"]'),
    ).toContainText("Promote to admin");

    // Clean up: remove the user from the org
    await requesterMembership.locator('button[value="removeuser"]').click();
  });

  test("admin role assigned after acceptance", async ({
    page,
  }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");

    // Defensive cleanup: revoke any stale pending invitations
    while (await page.locator('button[value="revokeinvite"]').count()) {
      await page.locator('button[value="revokeinvite"]').first().click();
      await page.goto("/organizations/e2e-public-org/manage-members/");
    }

    // Remove e2e-regular from org if they're already a member
    const staleMembership = page.locator(".membership", {
      has: page.locator("h3", { hasText: "e2e-regular" }),
    });
    if ((await staleMembership.count()) > 0) {
      await staleMembership.locator('button[value="removeuser"]').click();
      await page.goto("/organizations/e2e-public-org/manage-members/");
    }

    // Send invitation with Admin role
    await page.locator("input[name='emails']").fill("e2e-regular@example.com");
    await page.locator("select[name='role']").selectOption("1");
    await page.locator('button[value="addmember"]').click();
    await expectFlashMessage(page, "success");

    // Verify pending invitation shows Admin badge
    await page.goto("/organizations/e2e-public-org/manage-members/");
    const pendingSection = page.locator("section#pending");
    await expect(pendingSection).toBeVisible();
    const pendingInvitation = pendingSection.locator(".invitation").first();
    await expect(pendingInvitation.locator(".orange.badge")).toBeVisible();
    await expect(pendingInvitation.locator(".orange.badge")).toContainText(
      "Admin",
    );

    // Login as the invited user and accept from their account page
    await login(page, "e2e-regular");
    await page.goto("/users/e2e-regular/");
    const invitation = page.locator(".invite", {
      has: page.locator("text=e2e-public-org"),
    });
    await invitation.locator('button[value="accept"]').click();
    await expectFlashMessage(page, "success");

    // Verify the user is an admin in the members list
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/manage-members/");
    const regularMembership = page.locator(".membership", {
      has: page.locator("h3", { hasText: "e2e-regular" }),
    });
    await expect(regularMembership).toBeVisible();
    await expect(
      regularMembership.locator('button[value="makeadmin"]'),
    ).toContainText("Demote to member");

    // Clean up: remove the user from the org
    await regularMembership.locator('button[value="removeuser"]').click();
  });
});

test.describe("Invitation & Request History", () => {
  // Clear any invitations left over from earlier tests so history counts are predictable
  test.beforeEach(() => {
    runManageCommand("seed_e2e_data --action clear_invitations");
  });

  test.describe("Org admin", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-admin");
    });

    test("can access invitation history page", async ({ page }) => {
      const response = await page.goto("/organizations/e2e-public-org/invitations/");
      expect(response?.status()).toBe(200);
      await expect(page.locator(".invitation-history-page")).toBeVisible();
      // After clearing invitations, the page shows an empty message
      await expect(page.locator(".empty-message")).toBeVisible();
    });

    test("can access request history page", async ({ page }) => {
      const response = await page.goto("/organizations/e2e-public-org/requests/");
      expect(response?.status()).toBe(200);
      await expect(page.locator(".invitation-history-page")).toBeVisible();
      // After clearing invitations, the page shows an empty message
      await expect(page.locator(".empty-message")).toBeVisible();
    });

    test("can navigate to history pages from manage-members page", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/manage-members/");

      // Verify history links exist in each section
      const invitationsLink = page.locator(
        'a[href$="/organizations/e2e-public-org/invitations/"]',
      );
      const requestsLink = page.locator(
        'a[href$="/organizations/e2e-public-org/requests/"]',
      );
      await expect(invitationsLink).toBeVisible();
      await expect(requestsLink).toBeVisible();

      // Click invitation history link and verify navigation
      await invitationsLink.first().click();
      await expect(page.locator(".invitation-history-page")).toBeVisible();
    });

    test("pending invitation appears in invitation history", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/manage-members/");

      // Send an email invitation to a known e2e user
      await page.locator("input[name='emails']").fill("e2e-regular@example.com");
      await page.locator('button[value="addmember"]').click();
      await expectFlashMessage(page, "success");

      // Verify it appears in invitation history with "pending" status
      await page.goto("/organizations/e2e-public-org/invitations/");
      await expect(page.locator(".invitation-history-table tbody tr")).toHaveCount(1, {
        timeout: 5_000,
      });
      await expect(
        page.locator("td.invitation-status.pending"),
      ).toBeVisible();
    });

    test("accepted invitation appears in invitation history", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/manage-members/");

      // Send an email invitation to a known e2e user
      await page.locator("input[name='emails']").fill("e2e-regular@example.com");
      await page.locator('button[value="addmember"]').click();
      await expectFlashMessage(page, "success");

      // Receiving user accepts it
      await login(page, "e2e-regular");
      await page.goto("/users/e2e-regular/invitations/");
      await page.locator('button[value="accept"]').click();
      await page.waitForLoadState("networkidle");

      // Verify it appears in invitation history with "accepted" status
      await login(page, "e2e-admin");
      await page.goto("/organizations/e2e-public-org/invitations/");
      await expect(page.locator(".invitation-history-table tbody tr")).toHaveCount(1, {
        timeout: 5_000,
      });
      await expect(
        page.locator("td.invitation-status.accepted"),
      ).toBeVisible();
    });

    test("withdrawn invitation appears in invitation history", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/manage-members/");

      // Send an email invitation
      await page.locator("input[name='emails']").fill("e2e-history-test@example.com");
      await page.locator('button[value="addmember"]').click();
      await expectFlashMessage(page, "success");

      // Revoke it
      await page.goto("/organizations/e2e-public-org/manage-members/");
      await page.locator('button[value="revokeinvite"]').first().click();
      await expectFlashMessage(page, "success");

      // Verify it appears in invitation history with "withdrawn" status
      await page.goto("/organizations/e2e-public-org/invitations/");
      await expect(page.locator(".invitation-history-table tbody tr")).toHaveCount(1, {
        timeout: 5_000,
      });
      await expect(
        page.locator("td.invitation-status.withdrawn"),
      ).toBeVisible();
    });

    test("declined invitation appears in invitation history", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/manage-members/");

      // Send an email invitation to a known e2e user
      await page.locator("input[name='emails']").fill("e2e-regular@example.com");
      await page.locator('button[value="addmember"]').click();
      await expectFlashMessage(page, "success");

      // Receiving user declines it
      await login(page, "e2e-regular");
      await page.goto("/users/e2e-regular/invitations/");
      await page.locator('button[value="reject"]').click();

      // Verify it appears in invitation history with "declined" status
      await login(page, "e2e-admin");
      await page.goto("/organizations/e2e-public-org/invitations/");
      await expect(page.locator(".invitation-history-table tbody tr")).toHaveCount(1, {
        timeout: 5_000,
      });
      await expect(
        page.locator("td.invitation-status.declined"),
      ).toBeVisible();
    });

    test("rejected join request appears in request history", async ({ page, browser }) => {
      // Login as requester and submit join request
      const requesterContext = await browser.newContext({ ignoreHTTPSErrors: true });
      const requesterPage = await requesterContext.newPage();
      await login(requesterPage, "e2e-requester");
      await requesterPage.goto("/organizations/e2e-public-org/");
      await requesterPage.locator("#join-org-button").click();

      const modal = requesterPage.locator("#join-request-modal-backdrop");
      await expect(modal).not.toHaveClass(/_cls-hide/);
      await modal.locator('button[name="action"][value="join"]').click();
      await expectFlashMessage(requesterPage, "success");
      await requesterContext.close();

      // Admin rejects the request
      await page.goto("/organizations/e2e-public-org/manage-members/");
      await expect(page.locator("section#requests")).toBeVisible();
      await page.locator('button[value="rejectinvite"]').first().click();
      await expectFlashMessage(page, "success");

      // Verify it appears in request history with "declined" status
      await page.goto("/organizations/e2e-public-org/requests/");
      await expect(page.locator(".invitation-history-table tbody tr")).toHaveCount(1, {
        timeout: 5_000,
      });
      await expect(
        page.locator("td.invitation-status.declined"),
      ).toBeVisible();
    });
  });

  test.describe("Non-admin member", () => {
    test("cannot access invitation history (403)", async ({ page }) => {
      await login(page, "e2e-member");
      const response = await page.goto("/organizations/e2e-public-org/invitations/");
      expect(response?.status()).toBe(403);
    });

    test("cannot access request history (403)", async ({ page }) => {
      await login(page, "e2e-member");
      const response = await page.goto("/organizations/e2e-public-org/requests/");
      expect(response?.status()).toBe(403);
    });
  });

  test.describe("MuckRock staff", () => {
    test("can access any org's invitation history", async ({ page }) => {
      await login(page, "e2e-staff");
      const response = await page.goto("/organizations/e2e-public-org/invitations/");
      expect(response?.status()).toBe(200);
      await expect(page.locator(".invitation-history-page")).toBeVisible();
    });

    test("can access any org's request history", async ({ page }) => {
      await login(page, "e2e-staff");
      const response = await page.goto("/organizations/e2e-public-org/requests/");
      expect(response?.status()).toBe(200);
      await expect(page.locator(".invitation-history-page")).toBeVisible();
    });
  });
});
