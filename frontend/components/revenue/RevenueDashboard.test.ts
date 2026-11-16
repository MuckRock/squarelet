import { describe, it, expect, vi } from "vitest";
import { flushSync, mount } from "svelte";
import RevenueDashboard from "./RevenueDashboard.svelte";
import { report } from "./report.fixture";

vi.mock("../kpis/TrendChart.svelte", async () => ({
  default: (await import("../kpis/TrendChart.stub.test.svelte")).default,
}));
vi.mock("./MrrByPlanChart.svelte", async () => ({
  default: (await import("../kpis/TrendChart.stub.test.svelte")).default,
}));
vi.mock("./FlowChart.svelte", async () => ({
  default: (await import("../kpis/TrendChart.stub.test.svelte")).default,
}));

function render() {
  const target = document.createElement("div");
  mount(RevenueDashboard, { target, props: { report } });
  return target;
}

const tiles = (target: HTMLElement) =>
  [...target.querySelectorAll(".tile")].map((t) => t.textContent ?? "");

describe("RevenueDashboard", () => {
  it("headlines MRR to date against the start of the year", () => {
    const [mrr, subs] = tiles(render());

    expect(mrr).toContain("$16,490");
    expect(mrr).toContain("+26.3%");
    expect(subs).toContain("248");
    expect(subs).toContain("+33");
  });

  it("narrows the headline and table to the last 3 months", () => {
    const target = render();
    const three = target.querySelector<HTMLInputElement>('input[value="3"]')!;
    three.checked = true;
    three.dispatchEvent(new Event("change", { bubbles: true }));
    flushSync();

    expect(tiles(target)[2]).toContain("10.5%");
    const rows = [...target.querySelectorAll("table:not(.pending) tbody th")];
    expect(rows.map((r) => r.textContent?.trim())).toEqual([
      "Jul 2026",
      "Aug 2026",
      "Sep 2026",
      "Oct 2026 (to date)",
    ]);
  });

  it("totals subscriptions set to cancel across plans", () => {
    const target = render();

    expect(tiles(target)[4]).toContain("$3,810");
    expect(target.querySelector("table.pending tfoot")?.textContent).toContain(
      "21",
    );
    expect(target.querySelectorAll("table.pending tbody tr")).toHaveLength(2);
  });
});
