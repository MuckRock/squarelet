/* for /users/<username>/tokens/ */
import "@/css/sidebar_layout.css";
import "@/css/application_tokens.css";

import { initClipboardButtons } from "../clipboard";
import { initConfirmButtons } from "../confirm";

function main() {
  initClipboardButtons("Application token copied to clipboard.");
  initConfirmButtons();

  // Select the whole token when its field is focused
  document
    .querySelectorAll<HTMLInputElement>(".token-plaintext input")
    .forEach((input) => input.addEventListener("focus", () => input.select()));
}

window.addEventListener("DOMContentLoaded", main);
