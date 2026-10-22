import "@/css/sidebar_layout.css";
import "@/css/plan_card.css";
import "@/css/browse_plans.css";

document
  .querySelectorAll<HTMLButtonElement>(".plan-benefits-toggle")
  .forEach((toggle) => {
    const targetId = toggle.getAttribute("aria-controls");
    const list = document.getElementById(targetId);
    toggle.addEventListener("click", () => {
      const expanded = toggle.getAttribute("aria-expanded") === "true";
      toggle.setAttribute("aria-expanded", String(!expanded));
      list.hidden = expanded;
    });
  });
