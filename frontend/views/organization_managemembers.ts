/* for /organizations/<slug>/manage-members/ */
import "@/css/organization_managemembers.css";
import "@/css/user_list_item.css";
import "@/css/invitation_list_item.css";

function init() {
  const buttons = document.querySelectorAll("button.copy");

  buttons.forEach((buttton) => {
    buttton.addEventListener("click", (e) => {
      const link = buttton.getAttribute("value");
      if (link) {
        window?.navigator?.clipboard?.writeText(link);
      }
    });
  });
}

window.addEventListener("DOMContentLoaded", init);
