/**
 * Confirm buttons
 *
 * Asks for confirmation before `<button data-confirm="...">` submits its form.
 */

export function initConfirmButtons(root: ParentNode = document): void {
  root
    .querySelectorAll<HTMLButtonElement>("button[data-confirm]")
    .forEach((button) => {
      button.addEventListener("click", (e) => {
        if (!window.confirm(button.dataset.confirm ?? "")) {
          e.preventDefault();
        }
      });
    });
}
