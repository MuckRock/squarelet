import "@/css/organization_leave.css";

import OrgUserSelect from "../components/OrgUserSelect.svelte";
import { mount } from "svelte";

window.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("user-select");
  if (!el) return;

  mount(OrgUserSelect, {
    target: el,
    props: {
      organizationSlug: el.dataset.orgSlug,
      organizationName: el.dataset.orgName,
    },
  });
});
