import { test, expect, type Page } from "@playwright/test";
import { login, expectFlashMessage, resetLeaveOrgState } from "./helpers";

const LEAVE_ORG = "e2e-leave-org";
const LEAVE_URL = `/organizations/${LEAVE_ORG}/leave/`;
const ORG_URL = `/organizations/${LEAVE_ORG}/`;

/**
 * Locate a member's row within a rendered member list. Both the organization
 * detail page and the manage-members page render the same user_list_item
 * partial, so each member appears as a `.user` block containing a link to their
 * profile.
 */
export function memberRow(page: Page, username: string) {
  return page.locator(".user").filter({
    has: page.locator(`a[href="/users/${username}/"]`),
  });
}

/** Assert, via the DOM, that a user appears as an admin in the member list. */
export async function expectAdminBadge(page: Page, username: string) {
  await expect(
    memberRow(page, username).locator(".badge", { hasText: "Admin" }),
  ).toBeVisible();
}

/**
 * Assert, via the DOM, that a user appears in the member list as a regular
 * member (present, but without the Admin badge).
 */
export async function expectMemberWithoutAdmin(page: Page, username: string) {
  const row = memberRow(page, username);
  await expect(row).toBeVisible();
  await expect(row.locator(".badge", { hasText: "Admin" })).toHaveCount(0);
}

/** Assert, via the DOM, that a user is not present in the member list. */
export async function expectNotMember(page: Page, username: string) {
  await expect(memberRow(page, username)).toHaveCount(0);
}

test.describe("Leaving an organization as the sole admin", () => {
  // The reassign flow mutates memberships (removing the admin, promoting a
  // replacement), so establish a known state before each test and restore it
  // after so other specs are unaffected.
  test.beforeEach(() => {
    resetLeaveOrgState();
  });

  test.afterEach(() => {
    resetLeaveOrgState();
  });

  test("sole admin clicking Leave is redirected to the reassign form", async ({
    page,
  }) => {
    await login(page, "e2e-lone-admin");
    await page.goto(`/organizations/${LEAVE_ORG}/`);

    await page.locator('button[value="leave"]').click();

    await expect(page).toHaveURL(
      new RegExp(`/organizations/${LEAVE_ORG}/leave/`),
    );
    // The admin has not been removed yet — they must reassign or confirm first.
    await page.goto(ORG_URL);
    await expectAdminBadge(page, "e2e-lone-admin");
  });

  test("the reassign form renders the member-select widget", async ({
    page,
  }) => {
    await login(page, "e2e-lone-admin");
    await page.goto(LEAVE_URL);

    await expect(page.locator("#user-select")).toBeVisible();
    await expect(page.locator("#user-select input")).toBeVisible();
  });

  test("leaving without assigning removes the sole admin", async ({ page }) => {
    await login(page, "e2e-lone-admin");
    await page.goto(LEAVE_URL);

    // Submit without selecting a replacement.
    await page.locator('form.leave-form button[type="submit"]').click();

    await expectFlashMessage(page, "info");
    // The outgoing admin is no longer listed among the members. Verify as a
    // remaining member, since a non-member cannot view the member list.
    await login(page, "e2e-member");
    await page.goto(ORG_URL);
    await expectNotMember(page, "e2e-lone-admin");
  });

  test("assigning a replacement promotes them and removes the outgoing admin", async ({
    page,
  }) => {
    await login(page, "e2e-lone-admin");
    await page.goto(LEAVE_URL);

    // Open the member dropdown. The widget lists the organization's members
    // (fetched from the org-scoped search endpoint); pick one as the new admin.
    await page.locator("#user-select .sv-control").click();

    const option = page
      .locator("#user-select .sv-dropdown-content .sv-item--wrap")
      .filter({ hasText: "e2e-member" });
    await expect(option.first()).toBeVisible({ timeout: 10_000 });
    await option.first().click();

    await page.locator('form.leave-form button[type="submit"]').click();

    // Two info flashes appear (promotion + departure); assert at least one.
    await expect(page.locator("._cls-alerts .alert-info").first()).toBeVisible({
      timeout: 10_000,
    });
    // Replacement was promoted; the outgoing admin left. Verify as the newly
    // promoted admin, who can view the member list.
    await login(page, "e2e-member");
    await page.goto(ORG_URL);
    await expectAdminBadge(page, "e2e-member");
    await expectNotMember(page, "e2e-lone-admin");
  });

  test("cancelling returns to the organization without leaving", async ({
    page,
  }) => {
    await login(page, "e2e-lone-admin");
    await page.goto(LEAVE_URL);

    await page.locator(".leave-form .actions a.btn.ghost").click();

    await expect(page).toHaveURL(new RegExp(`/organizations/${LEAVE_ORG}/$`));
    // Cancelling lands back on the org page, where the admin is still listed.
    await expectAdminBadge(page, "e2e-lone-admin");
  });
});

test.describe("Demoting yourself as the sole admin", () => {
  const MANAGE_URL = `/organizations/${LEAVE_ORG}/manage-members/`;
  const DEMOTE_URL = `/organizations/${LEAVE_ORG}/demote/`;

  // The demote flow mutates memberships, so reset before and after each test.
  test.beforeEach(() => {
    resetLeaveOrgState();
  });

  test.afterEach(() => {
    resetLeaveOrgState();
  });

  test("sole admin clicking Demote is redirected to the demote form", async ({
    page,
  }) => {
    await login(page, "e2e-lone-admin");
    await page.goto(MANAGE_URL);

    const row = page.locator(".membership", {
      has: page.locator("h3", { hasText: "e2e-lone-admin" }),
    });

    await row.locator('button[value="makeadmin"]').click();

    await expect(page).toHaveURL(
      new RegExp(`/organizations/${LEAVE_ORG}/demote/`),
    );
    // Still an admin — the demote is deferred until they reassign or confirm.
    await page.goto(ORG_URL);
    await expectAdminBadge(page, "e2e-lone-admin");
  });

  test("demoting without assigning keeps the user as a member", async ({
    page,
  }) => {
    await login(page, "e2e-lone-admin");
    await page.goto(DEMOTE_URL);

    // Submit without selecting a replacement.
    await page.locator('form.leave-form button[type="submit"]').click();

    await expectFlashMessage(page, "info");
    // Demoted from admin, but still a member of the organization. The demoted
    // user remains a member, so they can still view the member list.
    await page.goto(ORG_URL);
    await expectMemberWithoutAdmin(page, "e2e-lone-admin");
  });

  test("assigning a replacement promotes them and demotes the outgoing admin", async ({
    page,
  }) => {
    await login(page, "e2e-lone-admin");
    await page.goto(DEMOTE_URL);

    // Open the member dropdown and pick a replacement admin.
    await page.locator("#user-select .sv-control").click();

    const option = page
      .locator("#user-select .sv-dropdown-content .sv-item--wrap")
      .filter({ hasText: "e2e-member" });
    await expect(option.first()).toBeVisible({ timeout: 10_000 });
    await option.first().click();

    await page.locator('form.leave-form button[type="submit"]').click();

    await expect(page.locator("._cls-alerts .alert-info").first()).toBeVisible({
      timeout: 10_000,
    });
    // Replacement promoted; outgoing admin demoted but still a member. The
    // demoted admin remains a member, so verify from their own view.
    await page.goto(ORG_URL);
    await expectAdminBadge(page, "e2e-member");
    await expectMemberWithoutAdmin(page, "e2e-lone-admin");
  });
});

test.describe("Leaving an organization as a regular member", () => {
  test.beforeEach(() => {
    resetLeaveOrgState();
  });

  test.afterEach(() => {
    resetLeaveOrgState();
  });

  test("a non-admin member leaves directly without the reassign form", async ({
    page,
  }) => {
    await login(page, "e2e-regular");
    await page.goto(`/organizations/${LEAVE_ORG}/`);

    await page.locator('button[value="leave"]').click();

    // Not redirected to the reassign form; the member is removed immediately.
    await expect(page).not.toHaveURL(
      new RegExp(`/organizations/${LEAVE_ORG}/leave/`),
    );
    // The member is gone from the list. Verify as the admin, who can view it.
    await login(page, "e2e-lone-admin");
    await page.goto(ORG_URL);
    await expectNotMember(page, "e2e-regular");
  });

  test("a non-sole-admin cannot access the reassign form (403)", async ({
    page,
  }) => {
    await login(page, "e2e-member");
    const response = await page.goto(LEAVE_URL);
    expect(response?.status()).toBe(403);
  });
});
