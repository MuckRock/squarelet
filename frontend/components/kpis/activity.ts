export interface Counts {
  users: number;
  multi: number;
}

export interface MonthActivity extends Counts {
  month: string;
  services: Record<string, Counts>;
}

export interface Activity {
  current_month: string;
  services: string[];
  months: MonthActivity[];
}

export type Measure = "users" | "pct";

export interface ChartRow {
  date: Date;
  [series: string]: Date | number | null;
}

export const TOTAL = "All services";

export function pct({ users, multi }: Counts): number | null {
  return users ? (multi / users) * 100 : null;
}

export function change(current: number | null, previous: number | null) {
  if (current === null || previous === null || previous === 0) return null;
  return ((current - previous) / previous) * 100;
}

export function monthDate(month: string): Date {
  const [year, index] = month.split("-").map(Number);
  return new Date(year, index - 1, 1);
}

export function completeMonths(activity: Activity): MonthActivity[] {
  return activity.months.filter((m) => m.month !== activity.current_month);
}

function measure(counts: Counts | undefined, kind: Measure): number | null {
  if (kind === "users") return counts?.users ?? 0;
  return counts ? pct(counts) : null;
}

/** One row per month, keyed by `TOTAL` and each service name. */
export function chartRows(
  months: MonthActivity[],
  services: string[],
  kind: Measure,
): ChartRow[] {
  return months.map((m) => {
    const row: ChartRow = {
      date: monthDate(m.month),
      [TOTAL]: measure(m, kind),
    };
    for (const service of services) {
      row[service] = measure(m.services[service], kind);
    }
    return row;
  });
}
