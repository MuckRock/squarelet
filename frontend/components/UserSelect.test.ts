import { describe, it, expect, vi, beforeEach } from "vitest";
import { flushSync, mount } from "svelte";
import UserSelect from "./UserSelect.svelte";

// Svelecte calls window.matchMedia which jsdom doesn't support
Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
});

describe("UserSelect", () => {
  beforeEach(() => {
    document.body.innerHTML = "";
  });

  it("renders a Svelecte component", () => {
    const target = document.createElement("div");
    document.body.appendChild(target);

    mount(UserSelect, { target, props: {} });

    // Svelecte renders an input element
    const input = target.querySelector("input");
    expect(input).toBeTruthy();
  });

  it("accepts an onChange callback prop", () => {
    const target = document.createElement("div");
    document.body.appendChild(target);
    const onChange = vi.fn();

    mount(UserSelect, {
      target,
      props: { onChange },
    });

    // Component mounts without error
    expect(target.querySelector("input")).toBeTruthy();
  });

  describe("invite by email", () => {
    async function search(query: string, results: object[]) {
      // Node's Request rejects jsdom's AbortSignal.
      vi.stubGlobal(
        "Request",
        class {
          constructor(public url: URL) {}
        },
      );
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(
            new Response(JSON.stringify({ count: results.length, results })),
          ),
      );
      const target = document.createElement("div");
      document.body.appendChild(target);
      mount(UserSelect, { target, props: {} });
      flushSync();

      const input = target.querySelector<HTMLInputElement>(
        "input.sv-input--text",
      )!;
      input.focus();
      input.value = query;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      flushSync();
      await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
      // let the response and fetchCallback settle
      await new Promise((resolve) => setTimeout(resolve, 0));
      flushSync();
      return target.querySelector<HTMLButtonElement>(".creatable-row")!;
    }

    beforeEach(() => {
      vi.unstubAllGlobals();
    });

    it("is offered when an email search finds nobody", async () => {
      const row = await search("new@example.com", []);
      expect(row.disabled).toBe(false);
    });

    it("is replaced by the user an email search finds", async () => {
      const row = await search("known@example.com", [
        { id: 1, name: "Known", username: "known" },
      ]);
      expect(row.disabled).toBe(true);
      expect(
        document.querySelector(".sv-dropdown-content")?.textContent,
      ).toContain("Known");
    });

    it("is withheld for a query that is not an email", async () => {
      const row = await search("nobody", []);
      expect(row.disabled).toBe(true);
    });
  });
});
