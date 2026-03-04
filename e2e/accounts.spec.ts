import { test, expect } from "@playwright/test";
import { E2E_PASSWORD, deleteTestUser } from "./helpers";

const SIGNUP_USER = "e2e-signup-user";
const SIGNUP_PASSWORD = "correct-horse-battery-staple";

test.describe("Signup", () => {
  test.afterAll(() => {
    deleteTestUser(SIGNUP_USER);
  });

  test.describe("Successful signup", () => {
    test("creates account and redirects away from signup", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/accounts/signup/");
      await page.locator("#signup_form input[name='email']").fill(`${SIGNUP_USER}@example.com`);
      await page.locator("#signup_form input[name='name']").fill("E2E Signup Test");
      await page.locator("#signup_form input[name='username']").fill(SIGNUP_USER);
      await page.locator("#signup_form input[name='password1']").fill(SIGNUP_PASSWORD);
      await page.locator("#signup_form input[name='tos']").check();
      const signupResponse = page.waitForResponse(
        (resp) => resp.url().includes("/accounts/signup/") && resp.request().method() === "POST",
      );
      await page.locator("#signup_form footer button.primary").click();
      expect((await signupResponse).status()).toBe(302);
      await page.waitForURL(/\/accounts\/onboard\//);
    });
  });

  test.describe("Validation errors", () => {
    test("duplicate username shows error", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/accounts/signup/");
      await page.locator("#signup_form input[name='email']").fill("unique-email@example.com");
      await page.locator("#signup_form input[name='name']").fill("Duplicate Test");
      await page.locator("#signup_form input[name='username']").fill("e2e-regular");
      await page.locator("#signup_form input[name='password1']").fill(E2E_PASSWORD);
      await page.locator("#signup_form input[name='tos']").check();
      await page.locator("#signup_form footer button.primary").click();
      // reload the signup page and see a validation error for the username field
      await expect(page).toHaveURL(/\/accounts\/signup\//);
      await expect(page.locator("#signup_form .errorlist")).toBeVisible();
    });

    test("missing TOS prevents submission", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/accounts/signup/");
      await page.locator("#signup_form input[name='email']").fill("tos-test@example.com");
      await page.locator("#signup_form input[name='name']").fill("TOS Test");
      await page.locator("#signup_form input[name='username']").fill("e2e-tos-test");
      await page.locator("#signup_form input[name='password1']").fill(E2E_PASSWORD);
      // intentionally skip checking tos — browser validation blocks submission
      await page.locator("#signup_form footer button.primary").click();
      // stay on the signup page and see a browser error for the tos field
      await expect(page).toHaveURL(/\/accounts\/signup\//);
    });

    test("empty form submission stays on signup page", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/accounts/signup/");
      // browser validation blocks submission of empty required fields
      await page.locator("#signup_form footer button.primary").click();
      // stay on the signup page and see a browser error for the tos field
      await expect(page).toHaveURL(/\/accounts\/signup\//);
    });
  });
});


test.describe("Login", () => {
  test.describe("Valid credentials", () => {
    test("login with username redirects away from login page", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/accounts/login/");
      await page.locator("#login_form input[name='login']").fill("e2e-regular");
      await page.locator("#login_form input[name='password']").fill(E2E_PASSWORD);
      const loginResponse = page.waitForResponse(
        (resp) => resp.url().includes("/accounts/login/") && resp.request().method() === "POST",
      );
      await page.locator("#login_form button.primary").click();
      expect((await loginResponse).status()).toBe(302);
      await page.waitForURL((url) => !url.pathname.includes("/accounts/login/"));
    });

    test("login with email redirects away from login page", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/accounts/login/");
      await page.locator("#login_form input[name='login']").fill("e2e-regular@example.com");
      await page.locator("#login_form input[name='password']").fill(E2E_PASSWORD);
      const loginResponse = page.waitForResponse(
        (resp) => resp.url().includes("/accounts/login/") && resp.request().method() === "POST",
      );
      await page.locator("#login_form button.primary").click();
      expect((await loginResponse).status()).toBe(302);
      await page.waitForURL((url) => !url.pathname.includes("/accounts/login/"));
    });
  });

  test.describe("Invalid credentials", () => {
    test("wrong password shows error", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/accounts/login/");
      await page.locator("#login_form input[name='login']").fill("e2e-regular");
      await page.locator("#login_form input[name='password']").fill("wrong-password");
      await page.locator("#login_form button.primary").click();
      await expect(page).toHaveURL(/\/accounts\/login\//);
      await expect(page.locator("#login_form .errorlist")).toBeVisible();
    });

    test("nonexistent user shows error", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/accounts/login/");
      await page.locator("#login_form input[name='login']").fill("no-such-user-xyz");
      await page.locator("#login_form input[name='password']").fill("any-password");
      await page.locator("#login_form button.primary").click();
      await expect(page).toHaveURL(/\/accounts\/login\//);
      await expect(page.locator("#login_form .errorlist")).toBeVisible();
    });
  });

  test.describe("Redirects", () => {
    test("unauthenticated user accessing protected page is sent to login", async ({
      page,
    }) => {
      await page.context().clearCookies();
      await page.goto("/organizations/~create");
      await expect(page).toHaveURL(/\/accounts\/login\//);
      await expect(page).toHaveURL(/next=.*organizations/);
    });

    test("next parameter is honored after login", async ({ page }) => {
      await page.context().clearCookies();
      await page.goto("/accounts/login/?next=/organizations/e2e-public-org/");
      await page.locator("#login_form input[name='login']").fill("e2e-regular");
      await page.locator("#login_form input[name='password']").fill(E2E_PASSWORD);
      const loginResponse = page.waitForResponse(
        (resp) => resp.url().includes("/accounts/login/") && resp.request().method() === "POST",
      );
      await page.locator("#login_form button.primary").click();
      expect((await loginResponse).status()).toBe(302);
      await expect(page).toHaveURL(/\/organizations\/e2e-public-org\//);
    });
  });
});
