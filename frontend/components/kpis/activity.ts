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

export interface ChartRow {
  date: Date;
  [series: string]: Date | number | null;
}

export const TOTAL = "All services";
export const MONTHLY = "Monthly";
export const AVERAGE = "3-month average";

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

/** Users per month, keyed by `TOTAL` and each service name. */
export function userRows(
  months: MonthActivity[],
  services: string[],
): ChartRow[] {
  return months.map((m) => {
    const row: ChartRow = { date: monthDate(m.month), [TOTAL]: m.users };
    for (const service of services) {
      row[service] = m.services[service]?.users ?? 0;
    }
    return row;
  });
}

/**
 * Multi-service share over the trailing `window` months, pooled so busy
 * months weigh more; null until a full window is in view.
 */
export function trailingShare(
  months: MonthActivity[],
  window = 3,
): (number | null)[] {
  return months.map((_, i) => {
    if (i < window - 1) return null;
    const span = months.slice(i - window + 1, i + 1);
    return pct({
      users: span.reduce((sum, m) => sum + m.users, 0),
      multi: span.reduce((sum, m) => sum + m.multi, 0),
    });
  });
}

/** Monthly multi-service share alongside its trailing average. */
export function shareRows(months: MonthActivity[]): ChartRow[] {
  const average = trailingShare(months);
  return months.map((m, i) => ({
    date: monthDate(m.month),
    [MONTHLY]: pct(m),
    [AVERAGE]: average[i],
  }));
}
