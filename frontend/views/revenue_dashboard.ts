import "layerchart/core.css";
import "@/css/dashboard.css";

import RevenueDashboard from "../components/revenue/RevenueDashboard.svelte";
import type { Report } from "../components/revenue/report";
import { mount } from "svelte";

window.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("revenue-dashboard");
  const data = document.getElementById("revenue-report");
  if (!el || !data) return;

  const report: Report = JSON.parse(data.textContent || "{}");
  mount(RevenueDashboard, { target: el, props: { report } });
});
