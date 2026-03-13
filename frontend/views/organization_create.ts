import "@/css/team_list_item.css";
import "@/css/organization_create.css";

import { mount } from "svelte";
import OrgNameSearch from "../components/OrgNameSearch.svelte";

window.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("org_name_search");
  if (el) {
    mount(OrgNameSearch, { target: el });
  }
});
