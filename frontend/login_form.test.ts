import { afterEach, describe, expect, it, vi } from "vitest";
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
  afterEach(() => {
    document.cookie = "csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/";
  });

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

  it("reloads instead of submitting when another tab rotated the token", () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { reload });
    document.cookie = "csrftoken=abc";
    const { form } = render();
    document.cookie = "csrftoken=xyz";
    expect(submit(form).defaultPrevented).toBe(true);
    expect(reload).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("reloads a stale tab as soon as it becomes visible again", () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { reload });
    document.cookie = "csrftoken=abc";
    render();
    document.cookie = "csrftoken=xyz";
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));
    expect(reload).toHaveBeenCalled();
    vi.unstubAllGlobals();
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
