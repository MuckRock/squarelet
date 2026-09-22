import { describe, it, expect, beforeEach, vi } from "vitest";

vi.mock("./alerts", () => ({ showAlert: vi.fn() }));

import { showAlert } from "./alerts";
import { initClipboardButtons } from "./clipboard";

describe("initClipboardButtons", () => {
  const writeText = vi.fn();

  beforeEach(() => {
    vi.mocked(showAlert).mockClear();
    writeText.mockReset().mockResolvedValue(undefined);
    Object.defineProperty(window.navigator, "clipboard", {
      value: { writeText },
      configurable: true,
    });
    document.body.innerHTML = `
      <form>
        <button data-clipboard value="mr_abc_secret">Copy</button>
        <button type="submit" value="other">Submit</button>
      </form>`;
  });

  it("copies the button value and shows the message", async () => {
    initClipboardButtons("Token copied.");
    document.querySelector<HTMLButtonElement>("[data-clipboard]")!.click();
    await Promise.resolve();
    expect(writeText).toHaveBeenCalledWith("mr_abc_secret");
    expect(showAlert).toHaveBeenCalledWith("Token copied.", "success", {
      canDismiss: true,
      autoDismiss: true,
    });
  });

  it("uses a default message", async () => {
    initClipboardButtons();
    document.querySelector<HTMLButtonElement>("[data-clipboard]")!.click();
    await Promise.resolve();
    expect(showAlert).toHaveBeenCalledWith(
      "Copied to clipboard.",
      "success",
      expect.anything(),
    );
  });

  it("does not submit the surrounding form", () => {
    initClipboardButtons();
    const submit = vi.fn((e: Event) => e.preventDefault());
    document.querySelector("form")!.addEventListener("submit", submit);
    document.querySelector<HTMLButtonElement>("[data-clipboard]")!.click();
    expect(submit).not.toHaveBeenCalled();
  });

  it("only binds data-clipboard buttons", () => {
    initClipboardButtons();
    const form = document.querySelector("form")!;
    form.addEventListener("submit", (e) => e.preventDefault());
    document.querySelector<HTMLButtonElement>('[type="submit"]')!.click();
    expect(writeText).not.toHaveBeenCalled();
  });

  it("reports copy failures", async () => {
    writeText.mockRejectedValue(new Error("denied"));
    initClipboardButtons();
    document.querySelector<HTMLButtonElement>("[data-clipboard]")!.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(showAlert).toHaveBeenCalledWith(
      "Could not copy to clipboard.",
      "error",
      expect.anything(),
    );
  });
});
