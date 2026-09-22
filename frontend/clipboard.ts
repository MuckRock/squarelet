/**
 * Clipboard buttons
 *
 * Binds `<button data-clipboard value="...">` elements to copy their value
 * and confirm with an alert. Used for invitation links and application tokens.
 */

import { showAlert } from "./alerts";

const ALERT_OPTIONS = { canDismiss: true, autoDismiss: true };

export function initClipboardButtons(
  message = "Copied to clipboard.",
  root: ParentNode = document,
): void {
  root
    .querySelectorAll<HTMLButtonElement>("button[data-clipboard]")
    .forEach((button) => {
      button.addEventListener("click", (e) => {
        e.preventDefault();
        const target = e.currentTarget as HTMLButtonElement;
        const copy = window?.navigator?.clipboard?.writeText(target.value);
        Promise.resolve(copy)
          .then(() => showAlert(message, "success", ALERT_OPTIONS))
          .catch(() =>
            showAlert("Could not copy to clipboard.", "error", ALERT_OPTIONS),
          );
      });
    });
}
