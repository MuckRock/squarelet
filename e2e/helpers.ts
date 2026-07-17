import { type Page, expect } from "@playwright/test";
import { execSync } from "child_process";

export const E2E_PASSWORD = "e2e-test-password";

const COMPOSE_E2E = "docker compose -f local.yml -f e2e.yml";

export async function login(page: Page, username: string) {
  // Clear cookies to ensure any existing session is removed,
  // otherwise allauth redirects authenticated users away from /accounts/login/
  await page.context().clearCookies();
  await page.goto("/accounts/login/");
  await page.locator("#login_form input[name='login']").fill(username);
  await page.locator("#login_form input[name='password']").fill(E2E_PASSWORD);
  const loginResponse = page.waitForResponse(
    (resp) => resp.url().includes("/accounts/login/") && resp.request().method() === "POST",
  );
  await page.locator("#login_form button.primary").click();
  expect((await loginResponse).status()).toBe(302);
  await page.waitForURL((url) => !url.pathname.includes("/accounts/login/"));
}

export async function expectFlashMessage(page: Page, level: string) {
  const alert = page.locator(`._cls-alerts .alert-${level}`);
  await expect(alert).toBeVisible({ timeout: 10_000 });
}

/**
 * Invite a user by email using the Svelecte-based UserSelect widget on the
 * manage-members page.  Types the email, waits for the creatable-row button to
 * become enabled (the email regex must match), clicks it to add the selection,
 * then clicks the "Send invites" submit button.
 */
export async function inviteByEmail(page: Page, email: string) {
  const input = page.locator("#user-select input");
  await input.fill(email);
  const createBtn = page.locator("button.creatable-row");
  await expect(createBtn).toBeEnabled({ timeout: 5_000 });
  await createBtn.click();
  await page.locator('button[value="addmember"]').click();
}

export function runManageCommand(args: string): string {
  return execSync(
    `${COMPOSE_E2E} exec -T squarelet_django /entrypoint python manage.py ${args}`,
    {
      stdio: "pipe",
      timeout: 30_000,
    },
  )
    .toString()
    .trim();
}

export function deleteTestUser(username: string) {
  runManageCommand(
    `shell -c "
from squarelet.users.models import User
from squarelet.organizations.models import Organization, OrganizationChangeLog
for u in User.objects.filter(username='${username}'):
    org_pks = list(u.organizations.values_list('pk', flat=True))
    OrganizationChangeLog.objects.filter(user=u).delete()
    OrganizationChangeLog.objects.filter(organization__in=org_pks).delete()
    u.delete()
    Organization.objects.filter(pk__in=org_pks).delete()
"`,
  );
}

export function deleteTestOrg(slug: string) {
  runManageCommand(
    `shell -c "from squarelet.organizations.models import Organization; Organization.objects.filter(slug__startswith='${slug}', individual=False).delete()"`,
  );
}

export function resetOrgProfileState(slug: string) {
  runManageCommand(
    `shell -c "
from squarelet.organizations.models import Organization, ProfileChangeRequest
ProfileChangeRequest.objects.filter(organization__slug='${slug}').delete()
Organization.objects.filter(slug='${slug}').update(city='')
"`,
  );
}

export function resetAutoJoinState(slug: string) {
  runManageCommand(
    `shell -c "
from squarelet.organizations.models import Organization
org = Organization.objects.get(slug='${slug}')
org.allow_auto_join = False
org.save()
org.domains.all().delete()
"`,
  );
}

/**
 * Reset all organization-to-organization (member org) state for e2e orgs:
 * clears pending/closed OrganizationInvitations and the member-org M2M links.
 */
export function resetMemberOrgState() {
  runManageCommand(
    `shell -c "
from squarelet.organizations.models import Organization
from squarelet.organizations.models.invitation import OrganizationInvitation
OrganizationInvitation.objects.filter(from_organization__slug__startswith='e2e-').delete()
OrganizationInvitation.objects.filter(to_organization__slug__startswith='e2e-').delete()
for org in Organization.objects.filter(slug__startswith='e2e-', individual=False):
    org.members.clear()
"`,
  );
}

/**
 * Create a pending member-org invitation from one org to another via the
 * management shell and return its UUID.  The inviting user is an admin of the
 * (collective) from-organization.  Useful for setting up state that is tedious
 * to build through the UI, e.g. testing the invitation landing page directly.
 */
export function createMemberOrgInvitation(
  fromSlug: string,
  toSlug: string,
): string {
  const out = runManageCommand(
    `shell -c "
from squarelet.organizations.models import Organization
from squarelet.organizations.models.invitation import OrganizationInvitation
from squarelet.organizations.choices import RelationshipType
group = Organization.objects.get(slug='${fromSlug}')
member = Organization.objects.get(slug='${toSlug}')
admin = group.users.filter(memberships__admin=True).first()
inv = OrganizationInvitation.objects.create(from_user=admin, from_organization=group, to_organization=member, relationship_type=RelationshipType.member)
print(inv.uuid)
"`,
  );
  const match = out.match(/[0-9a-f-]{36}/);
  if (!match) {
    throw new Error(
      `Failed to create member-org invitation ${fromSlug} -> ${toSlug}: ${out}`,
    );
  }
  return match[0];
}

/**
 * Accept a member-org invitation out-of-band via the management shell,
 * simulating the invitee accepting while another user's page is still stale.
 */
export function acceptMemberOrgInvitation(uuid: string) {
  runManageCommand(
    `shell -c "from squarelet.organizations.models.invitation import OrganizationInvitation; OrganizationInvitation.objects.get(uuid='${uuid}').accept()"`,
  );
}

/**
 * Directly establish a member-org relationship (group.members.add(member))
 * via the management shell, bypassing the invitation flow.  Useful for setting
 * up state for remove/leave tests.
 */
export function addMemberOrg(groupSlug: string, memberSlug: string) {
  runManageCommand(
    `shell -c "
from squarelet.organizations.models import Organization
group = Organization.objects.get(slug='${groupSlug}')
member = Organization.objects.get(slug='${memberSlug}')
group.members.add(member)
"`,
  );
}

/**
 * Drive the Svelecte-based org search widget on the manage-member-orgs page:
 * types the org name, waits for the matching option to appear in the dropdown,
 * and clicks it.  Selecting an org enables the "Send invite" submit button.
 */
export async function selectOrgInSearch(page: Page, name: string) {
  // Open/focus the widget via its control wrapper (the text input itself is
  // overlaid by the selection element and not directly clickable).
  await page.locator("#org_search .sv-control").click();
  const input = page.locator("#org_search input.sv-input--text");
  await input.fill(name);
  const option = page.locator(
    "#org_search .sv-dropdown-content .sv-item--wrap.in-dropdown",
    { has: page.locator("h4", { hasText: name }) },
  );
  await option.first().click({ timeout: 10_000 });
}
