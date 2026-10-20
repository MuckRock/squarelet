import { describe, expect, it, vi } from "vitest";
import { initLoginForm } from "./login_form";

function render() {
  document.body.innerHTML = `
    <form id="login_form" method="POST">
      <input name="login">
      <button class="button primary">Sign in</button>
    </form>`;
  const form = document.querySelector<HTMLFormElement>("form")!;
  initLoginForm(form);
  return { form, button: form.querySelector("button")! };
}

function submit(form: HTMLFormElement) {
  const event = new Event("submit", { cancelable: true });
  form.dispatchEvent(event);
  return event;
}

describe("login form", () => {
  it("lets the first submit through and disables the button", () => {
    const { form, button } = render();
    expect(submit(form).defaultPrevented).toBe(false);
    expect(button.disabled).toBe(true);
  });

  it("drops a second submit", () => {
    const { form } = render();
    submit(form);
    expect(submit(form).defaultPrevented).toBe(true);
  });

  it("reloads a page restored from the back-forward cache", () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { reload });
    render();
    window.dispatchEvent(
      new PageTransitionEvent("pageshow", { persisted: false }),
    );
    expect(reload).not.toHaveBeenCalled();
    window.dispatchEvent(
      new PageTransitionEvent("pageshow", { persisted: true }),
    );
    expect(reload).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
