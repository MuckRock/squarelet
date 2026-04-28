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

  // Hide the plain email fallback and disable its input so it doesn't submit
  const fallback = form.querySelector(".email-fallback");
  fallback?.setAttribute("hidden", "");
  fallback?.querySelector("input")?.setAttribute("disabled", "");

  // Create hidden inputs for emails and user IDs
  const emailsInput = document.createElement("input");
  emailsInput.type = "hidden";
  emailsInput.name = "emails";
  form.appendChild(emailsInput);

  const userIdsInput = document.createElement("input");
  userIdsInput.type = "hidden";
  userIdsInput.name = "user_ids";
  form.appendChild(userIdsInput);

  mount(UserSelect, {
    target: el,
    props: {
      onChange(next: Selection[]) {
        const emails = next
          .filter((sel) => sel.type === "email")
          .map((sel) => sel.email);
        const userIds = next
          .filter((sel) => sel.type === "user")
          .map((sel) => sel.id);
        emailsInput.value = emails.join(", ");
        userIdsInput.value = userIds.join(", ");
        if (submitBtn) submitBtn.disabled = next.length === 0;
      },
    },
  });

  if (submitBtn) submitBtn.disabled = true;
}

window.addEventListener("DOMContentLoaded", main);
