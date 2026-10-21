import "layerchart/core.css";
import "@/css/kpi_dashboard.css";

import KpiDashboard from "../components/kpis/KpiDashboard.svelte";
import type { Activity } from "../components/kpis/activity";
import { mount } from "svelte";

window.addEventListener("DOMContentLoaded", () => {
  const el = document.getElementById("kpi-dashboard");
  const data = document.getElementById("kpi-activity");
  if (!el || !data) return;

  const activity: Activity = JSON.parse(data.textContent || "{}");
  mount(KpiDashboard, { target: el, props: { activity } });
});
