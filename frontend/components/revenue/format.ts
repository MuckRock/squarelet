import { monthDate } from "./report";

const dollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const compactDollars = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  notation: "compact",
  maximumFractionDigits: 1,
});
const count = new Intl.NumberFormat("en-US");

export const money = (n: number) => dollars.format(n);
export const moneyTick = (n: number) => compactDollars.format(n);
export const signedMoney = (n: number) => `${n > 0 ? "+" : ""}${money(n)}`;
export const integer = (n: number) => count.format(Math.round(n));
export const signedInteger = (n: number) => `${n > 0 ? "+" : ""}${integer(n)}`;
export const percent = (n: number | null) =>
  n === null ? "—" : `${(n * 100).toFixed(1)}%`;

export const monthName = (month: string, options: Intl.DateTimeFormatOptions) =>
  monthDate(month).toLocaleDateString("en-US", options);
export const shortMonth = (month: string) =>
  monthName(month, { month: "short", year: "2-digit" });
export const longMonth = (month: string) =>
  monthName(month, { month: "short", year: "numeric" });

/** Month-axis ticks, thinned on narrow charts so labels never meet. */
export const monthTicks =
  (width: number) =>
  (scale: { domain: () => string[] }): string[] => {
    const months = scale.domain();
    const step = width < 600 ? Math.ceil(months.length / 4) : 1;
    return months.filter((_, i) => (months.length - 1 - i) % step === 0);
  };
