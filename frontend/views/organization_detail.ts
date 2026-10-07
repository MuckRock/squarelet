import "../css/organization_detail.css";
import "../css/sidebar_layout.css";
import "../css/user_list_item.css";
import "../css/user_detail.css";
import "../css/plan_card.css";
import "../css/organization_list.css";
import "../css/team_list_item.css";

// The join button opens a request modal instead of following its link.
document.addEventListener("DOMContentLoaded", () => {
  const joinButton = document.getElementById("join-org-button");
  const backdrop = document.getElementById("join-request-modal-backdrop");
  if (!joinButton || !backdrop) return;

  const open = () => {
    backdrop.classList.remove("_cls-hide");
    document.body.style.overflow = "hidden";
  };
  const close = () => {
    backdrop.classList.add("_cls-hide");
    document.body.style.overflow = "";
  };

  joinButton.addEventListener("click", (e) => {
    e.preventDefault();
    open();
  });

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) close();
  });

  backdrop
    .querySelectorAll('[data-dismiss="modal"]')
    .forEach((button) => button.addEventListener("click", close));

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !backdrop.classList.contains("_cls-hide")) close();
  });
});
