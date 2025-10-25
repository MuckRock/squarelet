/* for /organizations/<slug>/manage-members/ */
import { copyToClipboard, showAlert } from "../util";
import "@/css/organization_managemembers.css";
import "@/css/user_list_item.css";
import "@/css/invitation_list_item.css";

function main() {
  document.querySelectorAll("button[data-clipboard]").forEach((button) => {
    button.addEventListener("click", (e) => {
      e.preventDefault();
      const target = e.currentTarget as HTMLButtonElement;
      copyToClipboard(target.value);
      showAlert("Invitation link copied to clipboard.", "success", {
        canDismiss: true, autoDismiss: true
      });
    });
  });
}

window.addEventListener("DOMContentLoaded", main);
