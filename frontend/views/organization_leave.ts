import "@/css/organization_leave.css";

import OrgUserSelect from "../components/OrgUserSelect.svelte";
import { mount } from "svelte";

window.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("user-select");
  if (!el) return;

  const form = el.closest("form");
  const submitMessage = form.querySelector("button[type=submit] .message");

  mount(OrgUserSelect, {
    target: el,
    props: {
      organizationSlug: el.dataset.orgSlug,
      organizationName: el.dataset.orgName,
      onChange(user) {
        if (user) {
          submitMessage.textContent = "Assign and leave";
        } else {
          submitMessage.textContent = "Leave without assigning";
        }
      },
    },
  });
});
