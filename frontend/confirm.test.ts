import { describe, it, expect, beforeEach, vi } from "vitest";

import { initConfirmButtons } from "./confirm";

describe("initConfirmButtons", () => {
  let submitted: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    document.body.innerHTML = `
      <form>
        <button type="submit" data-confirm="Revoke this token?">Revoke</button>
      </form>`;
    submitted = vi.fn((e: Event) => e.preventDefault());
    document.querySelector("form")!.addEventListener("submit", submitted);
    initConfirmButtons();
  });

  it("submits when confirmed", () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    document.querySelector<HTMLButtonElement>("button")!.click();
    expect(window.confirm).toHaveBeenCalledWith("Revoke this token?");
    expect(submitted).toHaveBeenCalled();
  });

  it("cancels when declined", () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    document.querySelector<HTMLButtonElement>("button")!.click();
    expect(submitted).not.toHaveBeenCalled();
  });
});
