import { test, expect } from "./fixtures";
import { E2E_PASSWORD, login, newAnonContext } from "./helpers";

// Other apps send buyers to a plan link with purchase_redirect so that, once
// they have paid, they land back where they started.
const PURCHASE_REDIRECT = "https://dev.muckrock.com/accounts/";
const LEGACY_PLAN_URL = `/plans/organization/?purchase_redirect=${encodeURIComponent(
  PURCHASE_REDIRECT,
)}`;
const CHECKOUT_URL =
  /\/organizations\/e2e-[^/]+\/plans\/organization\/annual\/\?purchase_redirect=https/;

test.describe("Plan purchase redirects", () => {
  test.describe("Org admin", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-admin");
      await page.goto(LEGACY_PLAN_URL);
    });

    test("a legacy plan link lands on checkout carrying purchase_redirect", async ({
      page,
    }) => {
      await expect(page).toHaveURL(CHECKOUT_URL);
      await expect(page.locator("#subscribe-form")).toBeVisible();
    });

    test("every organization to switch to keeps purchase_redirect", async ({
      page,
    }) => {
      const options = page.locator("#organization-select option");
      await expect(options.first()).toBeAttached();
      const values = await options.evaluateAll((els) =>
        els.map((el) => (el as HTMLOptionElement).value),
      );
      expect(values.length).toBeGreaterThan(1);
      for (const value of values) {
        expect(value).toContain("purchase_redirect=https");
      }
    });
  });

  test.describe("Anonymous visitor", () => {
    test("logs in and continues to checkout carrying purchase_redirect", async ({
      browser,
    }) => {
      const anonContext = await newAnonContext(browser);
      const page = await anonContext.newPage();

      await page.goto(`https://dev.squarelet.com${LEGACY_PLAN_URL}`);
      await expect(page).toHaveURL(/\/accounts\/login\/\?next=/);

      await page.locator("#login_form input[name='login']").fill("e2e-admin");
      await page.locator("#login_form input[name='password']").fill(E2E_PASSWORD);
      await page.locator("#login_form button.primary").click();

      await expect(page).toHaveURL(CHECKOUT_URL);

      await anonContext.close();
    });
  });
});

test.describe("Enterprise plan page", () => {
  // Enterprise is sold through a conversation, so its page offers contact
  // links and the full description rather than a checkout.
  test.beforeEach(async ({ page }) => {
    await login(page, "e2e-admin");
    await page.goto("/organizations/e2e-public-org/plans/sunlight-enterprise/");
  });

  test("offers contact and learn-more links", async ({ page }) => {
    await expect(page.locator('a[href^="https://calendar.app.google/"]')).toBeVisible();
    await expect(
      page.locator('a[href="https://sunlightresearch.net/launch"]'),
    ).toBeVisible();
  });

  test("shows no checkout", async ({ page }) => {
    await expect(page.locator("#subscribe-form")).toHaveCount(0);
    await expect(page.locator("#card-form")).toHaveCount(0);
  });

  test("shows the full description", async ({ page }) => {
    await expect(page.locator("section.plan-long-description")).toBeVisible();
  });
});

test.describe("Paying by invoice", () => {
  // e2e-public-org has no card on file, so only an invoice lets it subscribe.
  const checkout = (interval: string) =>
    `/organizations/e2e-public-org/plans/organization/${interval}/`;

  test.beforeEach(async ({ page }) => {
    await login(page, "e2e-admin");
  });

  test("choosing invoice on an annual plan enables subscribing without a card", async ({
    page,
  }) => {
    await page.goto(checkout("annual"));
    const subscribe = page.locator("#subscribe-button");
    await expect(subscribe).toBeDisabled();

    await page.locator('input[name="payment_method"][value="invoice"]').check();

    await expect(subscribe).toBeEnabled();
    await expect(page.locator("#card-form")).toBeHidden();
  });

  test("choosing invoice swaps the card charge for the invoice terms", async ({
    page,
  }) => {
    await page.goto(checkout("annual"));
    const cardRow = page.locator('.checkout-row[data-payment-label="card"]');
    const invoiceRow = page.locator('.checkout-row[data-payment-label="invoice"]');
    await expect(cardRow).toBeVisible();
    await expect(invoiceRow).toBeHidden();

    await page.locator('input[name="payment_method"][value="invoice"]').check();

    await expect(cardRow).toBeHidden();
    await expect(invoiceRow).toBeVisible();
  });

  test("a monthly plan offers no invoice", async ({ page }) => {
    await page.goto(checkout("monthly"));
    await expect(
      page.locator('input[name="payment_method"][value="invoice"]'),
    ).toHaveCount(0);
  });
});
