import type { MonthRow, PendingRow, Report } from "./report";

// "All plans" from the Oct 21, 2026 Stripe export behind the original report.
// [month, subs_start, new, churned, subs_end, mrr_start, new_mrr, churned_mrr, mrr_end]
const EXPORT: [string, ...number[]][] = [
  ["2025-08", 204, 23, 19, 208, 10890, 1040, 820, 11110],
  ["2025-09", 208, 28, 21, 215, 11110, 2903, 960, 13053],
  ["2025-10", 215, 24, 18, 221, 13053, 1267, 720, 13600],
  ["2025-11", 221, 18, 22, 217, 13600, 1347, 1120, 13827],
  ["2025-12", 217, 29, 15, 231, 13827, 2420, 660, 15587],
  ["2026-01", 231, 17, 23, 225, 15587, 1047, 1360, 15273],
  ["2026-02", 225, 31, 23, 233, 15273, 1360, 1227, 15407],
  ["2026-03", 233, 25, 17, 241, 15407, 1060, 800, 15667],
  ["2026-04", 241, 29, 31, 239, 15667, 2067, 1540, 16193],
  ["2026-05", 239, 19, 29, 229, 16193, 1173, 1350, 16017],
  ["2026-06", 229, 32, 20, 241, 16017, 2427, 860, 17583],
  ["2026-07", 241, 26, 29, 238, 17583, 1670, 2060, 17193],
  ["2026-08", 238, 23, 25, 236, 17193, 1220, 2467, 15947],
  ["2026-09", 236, 29, 21, 244, 15947, 1620, 1237, 16330],
  ["2026-10", 244, 17, 13, 248, 16330, 1547, 1387, 16490],
];

export const months: MonthRow[] = EXPORT.map(
  ([
    month,
    subs_start,
    added,
    churned,
    subs_end,
    mrr_start,
    new_mrr,
    churned_mrr,
    mrr_end,
  ]) => ({
    segment: "all",
    segment_label: "All plans",
    month,
    partial: month === "2026-10",
    subs_start,
    new: added,
    churned,
    subs_end,
    mrr_start,
    new_mrr,
    churned_mrr,
    mrr_end,
    logo_churn: churned / subs_start,
    mrr_churn: churned_mrr / mrr_start,
  }),
);

const pending: PendingRow[] = [
  { segment: "all", segment_label: "All plans", subs: 21, mrr: 3810 },
  { segment: "professional", segment_label: "Professional", subs: 9, mrr: 360 },
  { segment: "sunlight", segment_label: "Sunlight", subs: 10, mrr: 3250 },
];

export const report: Report = {
  generated_at: "2026-10-21T12:00:00Z",
  current_month: "2026-10",
  segments: [
    ["professional", "Professional"],
    ["sunlight", "Sunlight"],
  ],
  months,
  pending,
};
