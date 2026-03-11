import { describe, it, expect, vi, beforeEach } from "vitest";
import { mount } from "svelte";
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
});
