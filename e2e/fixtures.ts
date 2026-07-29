import { test as base, expect } from "@playwright/test";
import { blockThirdPartyRequests } from "./helpers";

/**
 * The `test` every spec should import, in place of the one from
 * @playwright/test.  It overrides the built-in `context` fixture so that the
 * default `page` never blocks on a third-party request.  Contexts created by
 * hand inside a test get the same treatment via `newAnonContext`.
 */
export const test = base.extend({
  context: async ({ context }, use) => {
    await blockThirdPartyRequests(context);
    await use(context);
  },
});

export { expect };
