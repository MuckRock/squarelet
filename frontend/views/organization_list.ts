// use this on any page with an organization search
// there should be exactly **one** search field on the page

import { mount } from "svelte";
import OrgSearch from "../components/OrgSearch.svelte";

// start us up
window.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("org_search");
  if (el) {
    // @ts-ignore
    window.org_search = mount(OrgSearch, { target: el });
  }
});
