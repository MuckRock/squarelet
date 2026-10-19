<script lang="ts">
  import StatTile from "./StatTile.svelte";
  import TrendChart from "./TrendChart.svelte";
  import {
    type Activity,
    TOTAL,
    change,
    chartRows,
    completeMonths,
    monthDate,
    pct,
  } from "./activity";

  interface Props {
    activity: Activity;
  }

  let { activity }: Props = $props();

  // Fixed order so a service keeps its color as others come and go.
  const PALETTE = [
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#6250d6",
    "#e34948",
  ];
  const TOTAL_COLOR = "var(--gray-5)";

  const number = new Intl.NumberFormat("en-US");
  const formatUsers = (n: number) => number.format(Math.round(n));
  const formatPct = (n: number) => `${n.toFixed(1)}%`;
  const monthName = (month: string, options: Intl.DateTimeFormatOptions) =>
    monthDate(month).toLocaleDateString("en-US", options);

  const months = $derived(completeMonths(activity));
  const latest = $derived(months.at(-1));
  const previous = $derived(months.at(-2));

  const charted = $derived(activity.services.slice(0, PALETTE.length));
  const serviceSeries = $derived(
    charted.map((key, i) => ({ key, color: PALETTE[i] })),
  );
  const totalSeries = [{ key: TOTAL, color: TOTAL_COLOR }];

  let mauView: "total" | "services" = $state("total");
  let multiView: "total" | "services" = $state("total");
  const mauRows = $derived(chartRows(months, charted, "users"));
  const multiRows = $derived(chartRows(months, charted, "pct"));

  let picked: string | undefined = $state();
  const selected = $derived(picked ?? latest?.month ?? activity.current_month);
  const selectedMonth = $derived(
    activity.months.find((m) => m.month === selected),
  );
  const tableRows = $derived(
    activity.services
      .map((service) => ({
        service,
        ...(selectedMonth?.services[service] ?? { users: 0, multi: 0 }),
      }))
      .filter((row) => row.users > 0)
      .sort((a, b) => b.users - a.users),
  );
</script>

<div class="kpis">
  {#if !latest || !activity.months.some((m) => m.users > 0)}
    <p class="empty">
      No logins through Squarelet in the last {activity.months.length} months.
    </p>
  {:else}
    <section class="tiles" aria-label="Last complete month">
      <h2>{monthName(latest.month, { month: "long", year: "numeric" })}</h2>
      <div class="tile-grid">
        <StatTile
          label="Monthly active users"
          value={formatUsers(latest.users)}
          change={change(latest.users, previous?.users ?? null)}
        />
        <StatTile
          label="Multi-service users"
          value={formatUsers(latest.multi)}
          change={change(latest.multi, previous?.multi ?? null)}
        />
        <StatTile
          label="Multi-service share of MAU"
          value={formatPct(pct(latest) ?? 0)}
          change={change(pct(latest), previous ? pct(previous) : null)}
        />
      </div>
    </section>

    <section class="card">
      <header>
        <div>
          <h3>Monthly active users</h3>
          <p>Unique users who logged in to a service through Squarelet.</p>
        </div>
        {@render toggle("mau", mauView, (v) => (mauView = v))}
      </header>
      <TrendChart
        label="Monthly active users"
        data={mauRows}
        series={mauView === "total" ? totalSeries : serviceSeries}
        format={formatUsers}
      />
    </section>

    <section class="card">
      <header>
        <div>
          <h3>Multi-service usage</h3>
          <p>
            {#if multiView === "total"}
              Share of monthly active users who logged in to two or more
              services.
            {:else}
              Share of each service's monthly users who also logged in to
              another service.
            {/if}
          </p>
        </div>
        {@render toggle("multi", multiView, (v) => (multiView = v))}
      </header>
      <TrendChart
        label="Multi-service usage"
        data={multiRows}
        series={multiView === "total" ? totalSeries : serviceSeries}
        format={formatPct}
      />
    </section>

    <section class="card">
      <header>
        <div>
          <h3>By service</h3>
          <p>
            A user active on several services counts once in each row and once
            in the total.
          </p>
        </div>
        <label class="month">
          Month
          <select
            value={selected}
            onchange={(e) => (picked = e.currentTarget.value)}
          >
            {#each [...activity.months].reverse() as m (m.month)}
              <option value={m.month}>
                {monthName(m.month, {
                  month: "long",
                  year: "numeric",
                })}{m.month === activity.current_month ? " (to date)" : ""}
              </option>
            {/each}
          </select>
        </label>
      </header>
      <table>
        <thead>
          <tr>
            <th scope="col">Service</th>
            <th scope="col">Monthly active users</th>
            <th scope="col">Also used another service</th>
            <th scope="col">Share</th>
          </tr>
        </thead>
        <tbody>
          {#each tableRows as row (row.service)}
            <tr>
              <th scope="row">
                {#if charted.includes(row.service)}
                  <span
                    class="swatch"
                    style:background={PALETTE[charted.indexOf(row.service)]}
                  ></span>
                {/if}
                {row.service}
              </th>
              <td>{formatUsers(row.users)}</td>
              <td>{formatUsers(row.multi)}</td>
              <td>{formatPct(pct(row) ?? 0)}</td>
            </tr>
          {/each}
        </tbody>
        {#if selectedMonth}
          <tfoot>
            <tr>
              <th scope="row">{TOTAL}</th>
              <td>{formatUsers(selectedMonth.users)}</td>
              <td>{formatUsers(selectedMonth.multi)}</td>
              <td
                >{selectedMonth.users
                  ? formatPct(pct(selectedMonth) ?? 0)
                  : "—"}</td
              >
            </tr>
          </tfoot>
        {/if}
      </table>
    </section>
  {/if}
</div>

{#snippet toggle(
  name: string,
  value: string,
  set: (v: "total" | "services") => void,
)}
  <div class="toggle" role="radiogroup" aria-label="Breakdown">
    {#each [["total", "Total"], ["services", "By service"]] as [key, text] (key)}
      <label class:active={value === key}>
        <input
          type="radio"
          {name}
          value={key}
          checked={value === key}
          onchange={() => set(key as "total" | "services")}
        />
        {text}
      </label>
    {/each}
  </div>
{/snippet}

<style>
  .kpis {
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }
  h2 {
    margin: 0 0 0.75rem;
    font-size: var(--font-lg);
    color: var(--gray-5);
  }
  .tile-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(14rem, 1fr));
    gap: 1rem;
  }
  .card {
    padding: 1.25rem;
    border: 1px solid var(--gray-2);
    border-radius: var(--radius);
    background: var(--white);
  }
  .card header {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: flex-start;
    gap: 0.75rem 1.5rem;
    margin-bottom: 1rem;
  }
  h3 {
    margin: 0;
    font-size: var(--font-lg);
    color: var(--gray-5);
  }
  .card header p {
    margin: 0.25rem 0 0;
    color: var(--gray-4);
    font-size: var(--font-sm);
  }
  .toggle {
    display: inline-flex;
    border: 1px solid var(--gray-2);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .toggle label {
    padding: 0.375rem 0.75rem;
    font-size: var(--font-sm);
    color: var(--gray-4);
    cursor: pointer;
  }
  .toggle label.active {
    background: var(--blue-1);
    color: var(--blue-5);
    font-weight: var(--font-semibold);
  }
  .toggle label:has(input:focus-visible) {
    outline: 2px solid var(--primary);
    outline-offset: -2px;
  }
  .toggle input {
    position: absolute;
    opacity: 0;
    pointer-events: none;
  }
  .month {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: var(--font-sm);
    color: var(--gray-4);
  }
  table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--font-sm);
  }
  th,
  td {
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--gray-1);
    text-align: right;
    font-variant-numeric: tabular-nums;
  }
  th:first-child {
    text-align: left;
  }
  thead th {
    color: var(--gray-4);
    font-weight: var(--font-semibold);
    border-bottom-color: var(--gray-2);
  }
  tbody th {
    font-weight: var(--font-regular);
  }
  tfoot th,
  tfoot td {
    font-weight: var(--font-semibold);
    border-top: 1px solid var(--gray-2);
    border-bottom: none;
  }
  .swatch {
    display: inline-block;
    width: 0.625rem;
    height: 0.625rem;
    border-radius: 2px;
    margin-right: 0.375rem;
  }
  .empty {
    color: var(--gray-4);
  }
</style>
