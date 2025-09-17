import '@/css/team_list_item.css';
import '@/css/join_org.css';

import { mount } from "svelte";
import OrgSearch from "../components/OrgSearch.svelte";

// start us up
window.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("org_search");
  if (el) {
    mount(OrgSearch, { target: el });
  }
});
