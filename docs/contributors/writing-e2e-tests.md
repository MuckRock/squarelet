# Writing E2E Tests

This guide covers best practices for writing end-to-end tests with Playwright in Squarelet. The emphasis is on **robustness** — tests should verify application behavior, not specific copy or label text that changes with routine editing.

## Quick Start

E2E tests live in the `e2e/` directory and run against a real Docker environment with a dedicated test database. See the `e2e/global-setup.ts` and `e2e/global-teardown.ts` files for how the environment is provisioned.

Import `test` and `expect` from `./fixtures`, **not** from `@playwright/test`:

```ts
import { test, expect } from "./fixtures";
```

`e2e/fixtures.ts` wraps Playwright's `test` so that third-party requests are blocked. See [Third-Party Requests](#third-party-requests) for why this matters.

```bash
# Run with npx
npx playwright test
# Run using invoke
inv test-e2e

# Run a specific test file  (chromium only, matching CI)
npx playwright test e2e/organizations.spec.ts --project=chromium

# Run tests matching a name pattern
npx playwright test -g "admin can edit
# or with invoke
inv test-e2e --grep "admin can edit"
```

By default, Playwright runs in a headless mode, outputting test results to the command line. It also provides a visual headed mode, which opens a dedicated window for examining each run with console logs and screenshots from the running browser. This can be helpful for debugging tests and understanding which elements are visible on the tested pages.

```bash
# Run in headed mode
inv test-e2e --ui
```

## Core Principle: Select by Structure, Not by Content

Tests break when they depend on display text. Copy gets edited, labels get renamed, translations get added. **Your selectors should target the structural role of an element, not what it says.**

### Selector Priority

Use this order of preference when choosing how to target an element:

1. **`id` attribute** — Best for unique landmarks and sections.
   ```ts
   page.locator("#profile h3")
   page.locator("#join-org-button")
   page.locator("section#plan")
   ```

2. **`name` attribute** — Best for form inputs and action buttons.
   ```ts
   page.locator("input[name='emails']")
   page.locator("textarea[name='about']")
   page.locator("button[name='action'][value='join']")
   ```

3. **`value` attribute on buttons** — Best for form submit buttons that perform distinct actions.
   ```ts
   page.locator('button[value="leave"]')
   page.locator('button[value="addmember"]')
   page.locator('button[value="revokeinvite"]')
   ```

4. **`data-*` attributes** — Best for elements that lack a semantic attribute.
   ```ts
   page.locator("button[data-clipboard]")
   ```

5. **Structural CSS selectors** — Best for targeting elements by their position in the DOM hierarchy.
   ```ts
   page.locator("section#details button[type='submit']")
   page.locator("#members .user-list .user")
   page.locator("#login_form button.primary")
   ```

6. **`href` patterns** — Best for links, using substring or suffix matching.
   ```ts
   // Suffix match — URL ends with this path
   page.locator('a[href$="/organizations/e2e-public-org/manage-members/"]')

   // Substring match — URL contains this path segment
   page.locator('a[href*="/organizations/e2e-public-org/update/"]')
   ```

### What to Avoid

**Do not match on display text** unless the text itself is what you're testing.

```ts
// Bad — breaks if the button label changes from "Save" to "Update"
page.locator('button:has-text("Save")')

// Good — targets the form's submit button regardless of its label
page.locator("section#details button[type='submit']")
```

```ts
// Bad — breaks if heading copy changes
page.locator('h2:has-text("Members")')

// Good — targets the section by its id
page.locator("section#members h2")
```

**Exception:** Using `hasText` for scoping within a list is acceptable, because you're matching on *data*, not *copy*:

```ts
// Acceptable — finding a specific user's row by username (test data, not UI copy)
const row = page.locator(".membership", {
  has: page.locator("h3", { hasText: "e2e-requester" }),
});
await row.locator('button[value="removeuser"]').click();
```

## Test Structure

### Organize with `describe` Blocks

Group related tests by user role or workflow. Use `beforeEach` for shared setup like logging in.

```ts
test.describe("Organization Viewing", () => {
  test.describe("Org admin", () => {
    test.beforeEach(async ({ page }) => {
      await login(page, "e2e-admin");
    });

    test("sees edit profile link", async ({ page }) => {
      await page.goto("/organizations/e2e-public-org/");
      await expect(
        page.locator('a[href*="/organizations/e2e-public-org/update/"]'),
      ).toBeVisible();
    });
  });
});
```

### One Assertion Per Concept

Each test should verify a single behavior. Prefer multiple focused tests over one test with many assertions.

```ts
// Good — each test checks one thing
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
```

### Clean Up After Yourself

Tests run sequentially against a shared database. If a test modifies state, it must restore it.

```ts
test("toggling private hides org from anonymous users", async ({ page, browser }) => {
  await login(page, "e2e-admin");
  await page.goto("/organizations/e2e-public-org/update/");

  // Modify state
  await page.locator("section#details input[name='private']").check();
  await page.locator("section#details button[type='submit']").click();

  // ... verify the behavior ...

  // Undo the modification
  await page.goto("/organizations/e2e-public-org/update/");
  await page.locator("section#details input[name='private']").uncheck();
  await page.locator("section#details button[type='submit']").click();
});
```

## Using Helpers

Import shared helpers from `e2e/helpers.ts` instead of reimplementing common actions.

### `login(page, username)`

Logs in as one of the seeded test users. Clears cookies first so it works even if a different user was previously logged in.

```ts
import { login, expectFlashMessage } from "./helpers";

await login(page, "e2e-admin");
```

Available test users (seeded in `squarelet/core/management/commands/seed_e2e_data.py`):

| Username | Role |
|---|---|
| `e2e-staff` | MuckRock staff |
| `e2e-admin` | Admin of `e2e-public-org` and `e2e-private-org` |
| `e2e-member` | Member of `e2e-public-org` |
| `e2e-regular` | Signed in, no org membership |
| `e2e-requester` | Used for join request flows |

### `expectFlashMessage(page, level)`

Waits for a flash notification to appear. Use `"success"` or `"error"` as the level.

```ts
await page.locator('button[value="addmember"]').click();
await expectFlashMessage(page, "success");
```

### `newAnonContext(browser)`

Opens a fresh browser context for a second user, pre-configured for the dev environment. See [Testing Multiple User Contexts](#testing-multiple-user-contexts).

```ts
import { newAnonContext } from "./helpers";

const anonContext = await newAnonContext(browser);
const anonPage = await anonContext.newPage();
// ...
await anonContext.close();
```

### `runManageCommand(args)`

Runs a Django management command inside the Docker container. Useful for setting up or tearing down test state that's hard to create through the UI.

```ts
import { runManageCommand } from "./helpers";

runManageCommand("some_command --flag");
```

## Testing Multiple User Contexts

Use the `newAnonContext(browser)` helper to simulate a second user (e.g., an anonymous visitor) within the same test.

```ts
test("invite link is accessible to anonymous users", async ({ page, browser }) => {
  await login(page, "e2e-admin");
  // ... generate an invite link ...

  // Open a fresh anonymous browser context
  const anonContext = await newAnonContext(browser);
  const anonPage = await anonContext.newPage();
  await anonPage.goto(`https://dev.squarelet.com${invitationPath}`);

  await expect(anonPage.locator("form a[href*='signup']")).toBeVisible();

  await anonContext.close(); // always close extra contexts
});
```

Use the helper rather than calling `browser.newContext()` directly. It sets `ignoreHTTPSErrors: true` (the dev environment uses a self-signed certificate) and applies the same third-party request blocking the default `page` gets.

## Third-Party Requests

`base.html` loads Google Fonts, Plausible analytics, and Stripe.js on every page. `page.goto()` waits for the browser's `load` event, which waits on those subresources — so if any of them is slow or unreachable, the navigation stalls until the test's 30s budget is exhausted. The failure then surfaces on whatever step happened to be in flight, typically as a misleading "timed out waiting for locator" against an element that is plainly present in the failure screenshot.

To keep the suite independent of the public internet, `blockThirdPartyRequests()` in `e2e/helpers.ts` aborts those requests. It is applied automatically to:

- the default `page`, via the `context` fixture in `e2e/fixtures.ts`
- any context created with `newAnonContext(browser)`

None of the blocked resources affect application behavior under test. One caveat: `js.stripe.com` is blocked only because no test currently drives a Stripe card element. **A test that needs Stripe Elements must allow `js.stripe.com` through** by removing it from `THIRD_PARTY_HOSTS` or overriding the route in that spec.

## Assertions

### Checking Visibility

```ts
// Element should be present and visible
await expect(page.locator("section#plan")).toBeVisible();

// Element should NOT exist in the DOM
await expect(page.locator("section#plan")).toHaveCount(0);
```

Use `toHaveCount(0)` rather than `not.toBeVisible()` when asserting an element doesn't exist. `not.toBeVisible()` passes for hidden elements, while `toHaveCount(0)` ensures the element isn't in the DOM at all.

### Checking Text Content

Only check text when the content itself is what you're testing (e.g., verifying that submitted data appears correctly).

```ts
// Good — verifying user-entered data is displayed
await expect(page.locator("p.org-about")).toContainText("Updated by e2e test");

// Good — verifying the correct entity loaded
await expect(page.locator("#profile h3")).toContainText("e2e-public-org");
```

### Checking HTTP Status Codes

```ts
const response = await page.goto("/organizations/e2e-private-org/");
expect(response?.status()).toBe(404);
```

### Checking Element Count

```ts
// Verify the correct number of items rendered
await expect(page.locator("#members .user-list .user")).toHaveCount(2);
```

## Working with Modals

Wait for the modal to appear before interacting with it. Scope subsequent selectors to the modal element.

```ts
const modal = page.locator("#join-request-modal-backdrop");
await expect(modal).not.toHaveClass(/_cls-hide/);

// Interact within the modal's scope
await modal.locator('button[name="action"][value="join"]').click();
```

## Configuration

The Playwright config is in `playwright.config.ts`. Key settings:

- **`baseURL`**: `https://dev.squarelet.com` — all `page.goto("/path")` calls are relative to this.
- **`fullyParallel: false`**: Tests within a file run sequentially, since they share a database.
- **`timeout: 30_000`**: Each test has 30 seconds to complete.
- **`expect.timeout: 10_000`**: Each assertion retries for up to 10 seconds.
- **`navigationTimeout: 20_000`**: A stalled page load fails on its own, rather than silently consuming the test's budget and failing on a later step.
- **Screenshots and traces** are captured on failure for debugging.

## CI

E2E tests run in GitHub Actions on pull requests into `master` (see `.github/workflows/e2e.yml`). CI runs only the `chromium` project to keep pipeline times reasonable.

When a CI run fails:
1. Download the Playwright HTML report from the workflow's artifacts.
2. Check the screenshot and trace files for failing tests.
3. Review Docker logs (printed automatically on failure).

## Checklist for New Tests

- [ ] `test` and `expect` are imported from `./fixtures`, not `@playwright/test`
- [ ] Selectors use `id`, `name`, `value`, `data-*`, or structural CSS — not display text
- [ ] Tests clean up any state they modify
- [ ] `login()` and `expectFlashMessage()` helpers are used instead of reimplemented
- [ ] Extra browser contexts are created with `newAnonContext()` and closed after use
- [ ] Each test verifies one behavior
- [ ] Tests are grouped in `describe` blocks by role or workflow
