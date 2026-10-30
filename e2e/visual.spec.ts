import { type Locator, type Page } from "@playwright/test";
import { test, expect } from "./fixtures";
import { login, runManageCommand, totp, TOTP_SECRET } from "./helpers";

/**
 * Full-page screenshots of the pages a styling change can move, compared
 * against a baseline recorded from another ref with `inv test-visual`.
 * They assert nothing about behaviour; the other specs do that.
 */

let invitations: { member_invitation: string; group_invitation: string };

test.beforeAll(() => {
  const out = runManageCommand("seed_e2e_data --action seed_visual");
  invitations = JSON.parse(out.split("\n").pop() ?? "{}");
});

test.afterAll(() => {
  runManageCommand("seed_e2e_data --action teardown_visual");
});

async function snap(page: Page, name: string, mask: Locator[] = []) {
  // Vite injects CSS from JS in development, after the load event.
  await page.waitForLoadState("networkidle");
  // The pointer stays where the last click left it, hovering whatever the
  // next page puts there.
  await page.mouse.move(0, 0);
  await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
  const options = {
    fullPage: true,
    mask: [page.locator(".card-item-timestamp time"), ...mask],
    // Flash messages slide in and dismiss themselves on a timer.
    style: "._cls-alerts { display: none !important; }",
  };
  // Soft, so one changed page does not hide the rest of a multi-page test.
  await expect.soft(page).toHaveScreenshot(`${name}.png`, options);

  // toHaveScreenshot writes only the expected folder, so save this run's
  // screenshot beside it when it is a different commit.
  const { VISUAL_ACTUAL, VISUAL_EXPECTED } = process.env;
  if (VISUAL_ACTUAL !== VISUAL_EXPECTED) {
    const { project } = test.info();
    await page.screenshot({
      ...options,
      animations: "disabled",
      caret: "hide",
      path: `${project.testDir}/__screenshots__/${VISUAL_ACTUAL}/${project.name}/${name}.png`,
    });
  }
}

async function shoot(page: Page, path: string, name: string) {
  await page.goto(path);
  await snap(page, name);
}

async function loginWithTotp(page: Page, username: string) {
  await login(page, username);
  await page.waitForURL(/\/accounts\/2fa\/authenticate\//);
  await snap(page, "mfa-authenticate");
  await page.locator("input[name='code']").fill(totp(TOTP_SECRET));
  await page.locator("form button.primary[type='submit']").click();
  await page.waitForURL((url) => !url.pathname.includes("/2fa/authenticate"));
}

test.describe("Signed out", () => {
  test("sign in", async ({ page }) => {
    await shoot(page, "/accounts/login/", "login");
  });

  test("sign up", async ({ page }) => {
    await shoot(page, "/accounts/signup/", "signup");
  });

  test("select plan", async ({ page }) => {
    await shoot(page, "/selectplan/", "selectplan-signed-out");
  });

  test("plan detail", async ({ page }) => {
    await shoot(page, "/plans/professional/", "plan-professional-signed-out");
  });
});

test.describe("Reauthentication and MFA", () => {
  test("reauthenticate", async ({ page }) => {
    await login(page, "e2e-regular");
    await shoot(page, "/accounts/reauthenticate/", "reauthenticate");
  });

  test("TOTP setup", async ({ page }) => {
    await login(page, "e2e-regular");
    await page.goto("/accounts/2fa/totp/activate/");
    await snap(page, "mfa-totp-activate", [
      page.locator("#qr-code"),
      page.locator("#authenticator_secret input"),
    ]);
  });

  // One login per test: allauth rejects a TOTP code reused within its window.
  test("MFA user pages", async ({ page }) => {
    await loginWithTotp(page, "e2e-visual-mfa");
    await shoot(page, "/accounts/2fa/", "mfa-index");
    await shoot(page, "/accounts/2fa/reauthenticate/", "mfa-reauthenticate");
    await shoot(
      page,
      "/accounts/reauthenticate/",
      "reauthenticate-with-mfa-alternatives",
    );
  });
});

test.describe("Onboarding", () => {
  test("confirm email", async ({ page }) => {
    await login(page, "e2e-unverified");
    await shoot(page, "/accounts/onboard/", "onboard-confirm-email");
  });

  test("join organization", async ({ page }) => {
    await login(page, "e2e-visual-joiner");
    await shoot(page, "/accounts/onboard/", "onboard-join-org");
  });

  test("subscribe, both tabs", async ({ page }) => {
    await login(page, "e2e-admin");
    await shoot(
      page,
      "/accounts/onboard/?plan=professional",
      "onboard-subscribe-individual",
    );
    await page.locator(".tab.group").click();
    await expect(
      page.locator(".tab-group[data-active-tab='group']"),
    ).toBeVisible();
    await snap(page, "onboard-subscribe-group");
  });

  test("MFA opt-in, setup and confirm", async ({ page }) => {
    await login(page, "e2e-visual-onboard");
    await shoot(page, "/accounts/onboard/", "onboard-mfa-opt-in");

    await page.locator("button[name='enable_mfa'][value='yes']").click();
    const secret = page.locator("input[name='secret']");
    await expect(secret).toHaveCount(1);
    await snap(page, "onboard-mfa-setup", [page.locator(".qr-code-container img")]);

    await page.locator("input[name='code']").fill(totp(await secret.inputValue()));
    await page.locator("button[name='mfa_setup'][value='code']").click();
    await expect(page.locator("input[name='secret']")).toHaveCount(0);
    await snap(page, "onboard-mfa-confirm");
  });
});

test.describe("Plans", () => {
  test("select plan, free user", async ({ page }) => {
    await login(page, "e2e-regular");
    await shoot(page, "/selectplan/", "selectplan-free");
  });

  test("select plan, organization member", async ({ page }) => {
    await login(page, "e2e-visual-member");
    await shoot(page, "/selectplan/", "selectplan-org-member");
  });

  for (const slug of [
    "professional",
    "organization",
    "sunlight-essential",
    "sunlight-enterprise",
  ]) {
    test(`plan detail, ${slug}`, async ({ page }) => {
      await login(page, "e2e-regular");
      await shoot(page, `/plans/${slug}/`, `plan-${slug}`);
    });
  }
});

test.describe("Billing", () => {
  test("free user page", async ({ page }) => {
    await login(page, "e2e-regular");
    await shoot(page, "/users/e2e-regular/", "user-free");
  });

  test("free organization page", async ({ page }) => {
    await login(page, "e2e-admin");
    await shoot(page, "/organizations/e2e-public-org/", "org-free");
  });

  test.describe("Subscribed", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-visual-member");
    });

    test("user page", async ({ page }) => {
      await shoot(page, "/users/e2e-visual-member/", "user-subscribed");
    });

    test("organization page", async ({ page }) => {
      await shoot(page, "/organizations/e2e-visual-org/", "org-subscribed");
    });

    test("manage user subscriptions", async ({ page }) => {
      await shoot(
        page,
        "/users/e2e-visual-member/subscriptions/",
        "manage-subscriptions-user",
      );
    });

    test("manage organization subscriptions and plan modals", async ({
      page,
    }) => {
      await shoot(
        page,
        "/organizations/e2e-visual-org/subscriptions/",
        "manage-subscriptions-org",
      );

      await page.locator("a[href$='/end']").first().click();
      await page.waitForURL(/\/end$/);
      await snap(page, "modal-end-subscription");

      await page.goto("/organizations/e2e-visual-org/subscriptions/");
      await page.locator("a[href$='/cancel']").first().click();
      await page.waitForURL(/\/cancel$/);
      await snap(page, "modal-remove-plan");
    });
  });
});

test.describe("Invitations and requests", () => {
  test.beforeEach(async ({ page }) => {
    await login(page, "e2e-visual-member");
  });

  test("user invitations", async ({ page }) => {
    await shoot(page, "/users/e2e-visual-member/invitations/", "user-invitations");
  });

  test("user requests", async ({ page }) => {
    await shoot(page, "/users/e2e-visual-member/requests/", "user-requests");
  });

  test("organization invitations", async ({ page }) => {
    await shoot(page, "/organizations/e2e-visual-org/invitations/", "org-invitations");
  });

  test("organization requests", async ({ page }) => {
    await shoot(page, "/organizations/e2e-visual-org/requests/", "org-requests");
  });

  test("invitation detail", async ({ page }) => {
    await shoot(
      page,
      `/organizations/${invitations.member_invitation}/invitation/`,
      "invitation-detail",
    );
  });

  test("member organization invitation detail", async ({ page }) => {
    await shoot(
      page,
      `/organizations/${invitations.group_invitation}/member-org-invitation/`,
      "group-invitation-detail",
    );
  });
});
