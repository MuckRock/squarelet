export const ALL = "all";

export interface MonthRow {
  segment: string;
  segment_label: string;
  month: string;
  partial: boolean;
  subs_start: number;
  new: number;
  churned: number;
  subs_end: number;
  mrr_start: number;
  new_mrr: number;
  churned_mrr: number;
  mrr_end: number;
  logo_churn: number | null;
  mrr_churn: number | null;
}

export interface PendingRow {
  segment: string;
  segment_label: string;
  subs: number;
  mrr: number;
}

export interface Report {
  generated_at: string;
  current_month: string;
  segments: [string, string][];
  months: MonthRow[];
  pending: PendingRow[];
}

export type Window = 12 | 3;

export interface Churn {
  logo: number | null;
  mrr: number | null;
}

export function monthDate(month: string): Date {
  const [year, index] = month.split("-").map(Number);
  return new Date(year, index - 1, 1);
}

/** A segment's months, oldest first, ending with the month to date. */
export function segmentMonths(report: Report, segment = ALL): MonthRow[] {
  return report.months.filter((m) => m.segment === segment);
}

export function fullMonths(report: Report, segment = ALL): MonthRow[] {
  return segmentMonths(report, segment).filter((m) => !m.partial);
}

/** The months a window shows: its full months, then the month to date. */
export function visibleMonths(report: Report, window: Window): string[] {
  const rows = segmentMonths(report);
  return [
    ...rows.filter((m) => !m.partial).slice(-window),
    ...rows.filter((m) => m.partial),
  ].map((m) => m.month);
}

/**
 * Churn pooled over the months, so a busy month weighs more than a quiet
 * one: total lost over total live at the month starts.
 */
export function pooledChurn(rows: MonthRow[]): Churn {
  const sum = (key: keyof MonthRow) =>
    rows.reduce((total, row) => total + (row[key] as number), 0);
  const live = sum("subs_start");
  const mrr = sum("mrr_start");
  return {
    logo: live ? sum("churned") / live : null,
    mrr: mrr ? sum("churned_mrr") / mrr : null,
  };
}

/** Pooled churn over each month and the `span - 1` before it; null until a full span. */
export function trailingChurn(rows: MonthRow[], span = 3): (Churn | null)[] {
  return rows.map((_, i) =>
    i < span - 1 ? null : pooledChurn(rows.slice(i - span + 1, i + 1)),
  );
}

export interface WindowKpis {
  first: MonthRow;
  last: MonthRow;
  now: MonthRow;
  /** Fractional change in MRR from the window's start to now. */
  mrrChange: number | null;
  subsChange: number;
  churn: Churn;
}

/** Headline figures for the window's full months, measured to now. */
export function windowKpis(report: Report, window: Window): WindowKpis | null {
  const full = fullMonths(report).slice(-window);
  const now = segmentMonths(report).at(-1);
  if (!full.length || !now) return null;
  const first = full[0];
  return {
    first,
    last: full[full.length - 1],
    now,
    mrrChange: first.mrr_start
      ? (now.mrr_end - first.mrr_start) / first.mrr_start
      : null,
    subsChange: now.subs_end - first.subs_start,
    churn: pooledChurn(full),
  };
}
