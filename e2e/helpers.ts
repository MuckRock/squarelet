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
  await input.pressSequentially(email);
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
