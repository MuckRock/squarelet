import { beforeEach, describe, expect, it, vi } from "vitest";
import { initAvatarWidgets } from "./avatar_widget";

vi.mock("./css/avatar_widget.css", () => ({}));

function render(hasFile: boolean) {
  document.body.innerHTML = `
    <div data-avatar-widget data-has-file="${hasFile}" data-selected-alt="Selected avatar">
      <div class="wrapper ${hasFile ? "has-file" : ""}">
        <img data-avatar-preview alt="Current avatar" src="/current.png">
        <div data-avatar-preview></div>
      </div>
      <input type="file" data-avatar-input>
      <input type="checkbox" data-avatar-clear-checkbox ${hasFile ? "" : "disabled"}>
      <button type="button" data-avatar-clear-button ${hasFile ? "" : "disabled"}></button>
    </div>`;
  initAvatarWidgets();
  return {
    wrapper: document.querySelector<HTMLElement>(".wrapper")!,
    preview: document.querySelector<HTMLImageElement>("img")!,
    input: document.querySelector<HTMLInputElement>("[data-avatar-input]")!,
    checkbox: document.querySelector<HTMLInputElement>("[data-avatar-clear-checkbox]")!,
    button: document.querySelector<HTMLButtonElement>("[data-avatar-clear-button]")!,
  };
}

function choose(input: HTMLInputElement, file: File) {
  Object.defineProperty(input, "files", { value: [file], configurable: true });
  input.dispatchEvent(new Event("change"));
}

describe("avatar widget", () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => "blob:preview");
  });

  it("only offers to clear an avatar that exists", () => {
    expect(render(true).button.disabled).toBe(false);
    expect(render(false).button.disabled).toBe(true);
  });

  it("previews a chosen file and enables clearing it", () => {
    const { wrapper, preview, input, button } = render(false);
    choose(input, new File(["x"], "me.png", { type: "image/png" }));
    expect(preview.src).toBe("blob:preview");
    expect(preview.alt).toBe("Selected avatar");
    expect(wrapper.classList.contains("has-file")).toBe(true);
    expect(button.disabled).toBe(false);
  });

  it("choosing a file unticks a pending clear", () => {
    const { input, checkbox } = render(true);
    checkbox.checked = true;
    choose(input, new File(["x"], "me.png"));
    expect(checkbox.checked).toBe(false);
  });

  it("the clear button empties the preview and flags the avatar for removal on submit", () => {
    const { wrapper, input, checkbox, button } = render(true);
    button.click();
    expect(wrapper.classList.contains("has-file")).toBe(false);
    expect(input.value).toBe("");
    expect(checkbox.checked).toBe(true);
    expect(checkbox.disabled).toBe(false);
    expect(button.disabled).toBe(true);
  });

  it("unticking the clear checkbox re-enables the clear button only if an avatar was saved", () => {
    const saved = render(true);
    saved.checkbox.checked = true;
    saved.checkbox.dispatchEvent(new Event("change"));
    expect(saved.button.disabled).toBe(true);
    saved.checkbox.checked = false;
    saved.checkbox.dispatchEvent(new Event("change"));
    expect(saved.button.disabled).toBe(false);

    const unsaved = render(false);
    unsaved.checkbox.disabled = false;
    unsaved.checkbox.checked = true;
    unsaved.checkbox.dispatchEvent(new Event("change"));
    unsaved.checkbox.checked = false;
    unsaved.checkbox.dispatchEvent(new Event("change"));
    expect(unsaved.button.disabled).toBe(true);
  });
});
