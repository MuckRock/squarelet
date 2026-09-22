import "@/css/sidebar_layout.css";
import "@/css/organization_managemembers.css";
import "@/css/organization_list.css";
import "@/css/user_detail.css";
import "@/css/team_list_item.css";

import { mount } from "svelte";
import OrgSearch from "../components/OrgSearch.svelte";

// start us up
window.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("org_search");
  if (!el) return;

  const form = el.closest("form");
  const submitBtn = form.querySelector<HTMLButtonElement>(
    '[name="action"][value="send_invite"]',
  );

  mount(OrgSearch, {
    target: el,
    props: {
      name: "to_organization",
      onChange: (org) => {
        submitBtn.disabled = !org;
      },
    },
  });
});
