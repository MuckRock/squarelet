/** Read Django's CSRF cookie, which changes only when sign-in rotates it. */
function csrfCookie(): string | undefined {
  for (const part of document.cookie.split("; ")) {
    const [name, value] = part.split("=");
    if (name === "csrftoken") return value;
  }
  return undefined;
}

/** Guard a sign-in form against being submitted with a stale CSRF token. */
export function initLoginForm(form: HTMLFormElement) {

  // Make a re-rendered POST result a plain GET entry so back, refresh or reload can't resubmit it
  window.history.replaceState(window.history.state, "", window.location.href);

  // A different tab signing in rotates this before we submit.
  const cookieAtLoad = csrfCookie();
  let submitted = false;

  form.addEventListener("submit", (e) => {
    if (submitted) {
      e.preventDefault();
      return;
    }
    if (csrfCookie() !== cookieAtLoad) {
      e.preventDefault();
      window.location.reload();
      return;
    }
    submitted = true;
    form
      .querySelectorAll<HTMLButtonElement>("button:not([type=button])")
      .forEach((button) => (button.disabled = true));
  });

  // Catches a stale tab before the user retypes a code into a doomed form.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && csrfCookie() !== cookieAtLoad) {
      window.location.reload();
    }
  });

  // A page restored from the back-forward cache holds a token from before
  // the sign-in that followed it.
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) window.location.reload();
  });
}
