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
  await page.locator("#login_form button.primary").click();
  await page.waitForURL((url) => !url.pathname.includes("/accounts/login/"));
}

export async function expectFlashMessage(page: Page, text: string) {
  const alert = page.locator("._cls-alerts ._cls-middleAlign", {
    hasText: text,
  });
  await expect(alert).toBeVisible({ timeout: 10_000 });
}

export function runManageCommand(args: string): string {
  return execSync(`${COMPOSE_E2E} exec -T squarelet_django python manage.py ${args}`, {
    stdio: "pipe",
    timeout: 30_000,
  })
    .toString()
    .trim();
}
