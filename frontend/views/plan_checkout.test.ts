import { describe, it, expect, beforeAll, vi } from "vitest";

describe("plan checkout waitlist", () => {
  const fetchMock = vi.fn();

  beforeAll(async () => {
    // The waitlist form carries an input named "action", which shadows
    // `form.action`.
    document.body.innerHTML = `
      <form id="subscribe-form" method="post" action="/organizations/org/plans/tier/annual/">
        <input type="hidden" name="action" value="waitlist" />
        <button type="submit" id="subscribe-button">Join the waitlist</button>
        <div id="subscribe-errors"></div>
      </form>
    `;
    // Browsers let the input shadow `form.action`; jsdom doesn't, so do it here.
    const form = document.getElementById("subscribe-form") as HTMLFormElement;
    Object.defineProperty(form, "action", {
      value: form.querySelector('input[name="action"]'),
    });
    fetchMock.mockResolvedValue({
      status: 200,
      json: () => Promise.resolve({ redirect: "/done/" }),
    });
    vi.stubGlobal("fetch", fetchMock);
    await import("./plan_checkout");
  });

  it("posts to the form's URL", () => {
    const form = document.getElementById("subscribe-form") as HTMLFormElement;
    form.dispatchEvent(new Event("submit", { cancelable: true }));

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][0]).toBe(
      "/organizations/org/plans/tier/annual/",
    );
  });
});
