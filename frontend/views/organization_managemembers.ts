/* for /organizations/<slug>/manage-members/ */
import "@/css/organization_managemembers.css";
import "@/css/user_list_item.css";
import "@/css/invitation_list_item.css";

function main() {
  document.querySelectorAll("button[data-clipboard]").forEach((button) => {
    button.addEventListener("click", (e) => {
      e.preventDefault();
      const target = e.currentTarget as HTMLButtonElement;
      window?.navigator?.clipboard?.writeText(target.value);
    });
  });
}

window.addEventListener("DOMContentLoaded", main);
