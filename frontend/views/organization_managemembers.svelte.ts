/* for /organizations/<slug>/manage-members/ */
import type { Selection } from "../types";

import "@/css/sidebar_layout.css";
import "@/css/organization_managemembers.css";
import "@/css/user_list_item.css";
import "@/css/invitation_list_item.css";

import { mount } from "svelte";
import { showAlert } from "../alerts";
import UserSelect from "../components/UserSelect.svelte";

function main() {
  // Clipboard buttons for invite links
  document.querySelectorAll("button[data-clipboard]").forEach((button) => {
    button.addEventListener("click", (e) => {
      e.preventDefault();
      const target = e.currentTarget as HTMLButtonElement;
      window?.navigator?.clipboard?.writeText(target.value);
      showAlert("Invitation link copied to clipboard.", "success", {
        canDismiss: true,
        autoDismiss: true,
      });
    });
  });

  // Mount UserSelect onto the invite form
  const el = document.getElementById("user-select");
  if (!el) return; // no mount point — form works as plain HTML fallback

  const form = el.closest("form") as HTMLFormElement;
  const submitBtn = form.querySelector<HTMLButtonElement>(
    '[name="action"][value="addmember"]',
  );

  // Hide the plain email fallback, show the Svelte widget
  form.querySelector(".email-fallback")?.setAttribute("hidden", "");

  // Create a hidden input to hold resolved emails for form submission
  const hiddenInput = document.createElement("input");
  hiddenInput.type = "hidden";
  hiddenInput.name = "emails";
  form.appendChild(hiddenInput);

  mount(UserSelect, {
    target: el,
    props: {
      onChange(next: Selection[]) {
        // Resolve all selections to email addresses
        const emails = next.map((sel) =>
          sel.type === "email" ? sel.email : sel.email,
        );
        hiddenInput.value = emails.join(", ");
        if (submitBtn) submitBtn.disabled = next.length === 0;
      },
    },
  });

  if (submitBtn) submitBtn.disabled = true;
}

window.addEventListener("DOMContentLoaded", main);
