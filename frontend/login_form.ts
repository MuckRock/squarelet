/** Guard a sign-in form against being submitted with a stale CSRF token. */
export function initLoginForm(form: HTMLFormElement) {
  // A second submit carries the token the first one's login rotated away.
  let submitted = false;
  form.addEventListener("submit", (e) => {
    if (submitted) {
      e.preventDefault();
      return;
    }
    submitted = true;
    form
      .querySelectorAll<HTMLButtonElement>("button:not([type=button])")
      .forEach((button) => (button.disabled = true));
  });

  // A page restored from the back-forward cache holds a token from before
  // the sign-in that followed it.
  window.addEventListener("pageshow", (e) => {
    if (e.persisted) window.location.reload();
  });
}
