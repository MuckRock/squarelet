import { describe, it, expect } from "vitest";
import { trailingChurn, visibleMonths, windowKpis } from "./report";
import { months, report } from "./report.fixture";

describe("windowKpis", () => {
  it("pools churn over the last 12 full months", () => {
    const kpis = windowKpis(report, 12)!;

    expect(kpis.first.month).toBe("2025-10");
    expect(kpis.last.month).toBe("2026-09");
    expect(kpis.churn.logo).toBeCloseTo(0.0987, 4);
    expect(kpis.churn.mrr).toBeCloseTo(0.0831, 4);
  });

  it("measures change from the window's start to the month to date", () => {
    const kpis = windowKpis(report, 12)!;

    expect(kpis.mrrChange).toBeCloseTo(0.2633, 4);
    expect(kpis.subsChange).toBe(33);
  });

  it("pools churn over the last 3 full months", () => {
    const kpis = windowKpis(report, 3)!;

    expect(kpis.first.month).toBe("2026-07");
    expect(kpis.churn.logo).toBeCloseTo(0.1049, 4);
    expect(kpis.churn.mrr).toBeCloseTo(0.1136, 4);
  });

  it("has nothing to headline before a full month", () => {
    const fresh = { ...report, months: months.slice(-1) };

    expect(windowKpis(fresh, 12)).toBeNull();
  });
});

describe("visibleMonths", () => {
  it("shows the window's full months and the month to date", () => {
    expect(visibleMonths(report, 3)).toEqual([
      "2026-07",
      "2026-08",
      "2026-09",
      "2026-10",
    ]);
  });
});

describe("trailingChurn", () => {
  it("pools each month with the two before it", () => {
    const full = months.filter((m) => !m.partial);
    const trailing = trailingChurn(full);

    expect(trailing[0]).toBeNull();
    expect(trailing[1]).toBeNull();
    // Aug-Oct 2025: (19 + 21 + 18) / (204 + 208 + 215)
    expect(trailing[2]!.logo).toBeCloseTo(58 / 627);
    expect(trailing.at(-1)!.logo).toBeCloseTo(0.1049, 4);
  });
});
