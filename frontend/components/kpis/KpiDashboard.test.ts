import { describe, it, expect, vi } from "vitest";
import { flushSync, mount } from "svelte";
import KpiDashboard from "./KpiDashboard.svelte";
import {
  type Activity,
  type MonthActivity,
  completeMonths,
  trailingShare,
  userRows,
} from "./activity";

vi.mock("./TrendChart.svelte", async () => ({
  default: (await import("./TrendChart.stub.test.svelte")).default,
}));

const activity: Activity = {
  current_month: "2026-03",
  services: ["MuckRock", "DocumentCloud"],
  months: [
    {
      month: "2026-01",
      users: 4,
      multi: 1,
      services: {
        MuckRock: { users: 3, multi: 1 },
        DocumentCloud: { users: 2, multi: 1 },
      },
    },
    {
      month: "2026-02",
      users: 5,
      multi: 2,
      services: {
        MuckRock: { users: 4, multi: 2 },
        DocumentCloud: { users: 3, multi: 2 },
      },
    },
    {
      month: "2026-03",
      users: 1,
      multi: 0,
      services: { MuckRock: { users: 1, multi: 0 } },
    },
  ],
};

describe("KpiDashboard", () => {
  it("headlines the last complete month, not the month to date", () => {
    const target = document.createElement("div");
    mount(KpiDashboard, { target, props: { activity } });

    const tiles = [...target.querySelectorAll(".tile")].map(
      (t) => t.textContent,
    );
    expect(target.querySelector("h2")?.textContent).toBe("February 2026");
    expect(tiles[0]).toContain("5");
    expect(tiles[0]).toContain("+25.0%");
    expect(tiles[2]).toContain("40.0%");
  });

  it("lists each service for the selected month with a total", () => {
    const target = document.createElement("div");
    mount(KpiDashboard, { target, props: { activity } });

    const rows = [...target.querySelectorAll("tbody tr")].map((r) =>
      [...r.children].map((c) => c.textContent?.trim()),
    );
    expect(rows).toEqual([
      ["MuckRock", "4", "2", "50.0%"],
      ["DocumentCloud", "3", "2", "66.7%"],
    ]);
    expect(target.querySelector("tfoot")?.textContent).toContain("40.0%");

    const select = target.querySelector("select")!;
    select.value = "2026-03";
    select.dispatchEvent(new Event("change", { bubbles: true }));
    flushSync();
    expect(target.querySelectorAll("tbody tr")).toHaveLength(1);
  });

  it("still headlines a month nobody logged in", () => {
    const target = document.createElement("div");
    const quiet = {
      ...activity,
      months: activity.months.map((m) =>
        m.month === "2026-02" ? { ...m, users: 0, multi: 0, services: {} } : m,
      ),
    };
    mount(KpiDashboard, { target, props: { activity: quiet } });

    expect(target.querySelector("h2")?.textContent).toBe("February 2026");
    expect(target.querySelector(".tile")?.textContent).toContain("-100.0%");
  });

  it("charts multi-service usage in total only", () => {
    const target = document.createElement("div");
    mount(KpiDashboard, { target, props: { activity } });

    const section = target
      .querySelector('figure[aria-label="Multi-service usage"]')!
      .closest("section")!;
    expect(section.querySelector(".toggle")).toBeNull();
  });

  it("says so when nobody has logged in", () => {
    const target = document.createElement("div");
    const empty = {
      ...activity,
      months: activity.months.map((m) => ({
        ...m,
        users: 0,
        multi: 0,
        services: {},
      })),
    };
    mount(KpiDashboard, { target, props: { activity: empty } });

    expect(target.textContent).toContain("No logins");
    expect(target.querySelector("table")).toBeNull();
  });
});

describe("userRows", () => {
  it("plots a month without a service's users as zero users", () => {
    const march = userRows(activity.months, activity.services).at(-1)!;

    expect(march.DocumentCloud).toBe(0);
  });

  it("charts complete months only", () => {
    const rows = userRows(completeMonths(activity), activity.services);

    expect(rows.map((r) => r["All services"])).toEqual([4, 5]);
  });
});

describe("trailingShare", () => {
  const months = (counts: [number, number][]): MonthActivity[] =>
    counts.map(([users, multi], i) => ({
      month: `2026-0${i + 1}`,
      users,
      multi,
      services: {},
    }));

  it("pools the window rather than averaging monthly shares", () => {
    // 10/12 pooled, where averaging 50%, 90% and 0/0 would give 70%.
    const share = trailingShare(
      months([
        [2, 1],
        [10, 9],
        [0, 0],
      ]),
    );

    expect(share[2]).toBeCloseTo((10 / 12) * 100);
  });

  it("leaves months before a full window blank", () => {
    const share = trailingShare(
      months([
        [4, 1],
        [4, 2],
        [4, 3],
        [4, 4],
      ]),
    );

    expect(share).toEqual([null, null, 50, 75]);
  });
});
