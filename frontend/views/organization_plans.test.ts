import { describe, it, expect, beforeAll } from "vitest";

describe("plan benefits toggle", () => {
  let toggle: HTMLButtonElement;
  let list: HTMLElement;

  beforeAll(async () => {
    document.body.innerHTML = `
      <button class="plan-benefits-toggle" aria-expanded="false" aria-controls="benefits">Benefits</button>
      <ul id="benefits" hidden><li>One</li></ul>
    `;
    await import("./organization_plans");
    toggle = document.querySelector(".plan-benefits-toggle");
    list = document.getElementById("benefits");
  });

  it("opens the list and reports it expanded", () => {
    toggle.click();
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(list.hidden).toBe(false);
  });

  it("closes it again on a second click", () => {
    toggle.click();
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(list.hidden).toBe(true);
  });
});
