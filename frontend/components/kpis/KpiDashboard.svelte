<script lang="ts">
  import StatTile from "./StatTile.svelte";
  import Toggle from "./Toggle.svelte";
  import TrendChart from "./TrendChart.svelte";
  import {
    type Activity,
    AVERAGE,
    MONTHLY,
    TOTAL,
    change,
    completeMonths,
    monthDate,
    pct,
    shareRows,
    userRows,
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
  const shareSeries = [
    { key: MONTHLY, color: "var(--gray-3)", width: 1.5 },
    { key: AVERAGE, color: "var(--blue-4)", width: 2.5 },
  ];

  let mauView: "total" | "services" = $state("total");
  const mauRows = $derived(userRows(months, charted));
  const multiRows = $derived(shareRows(months));

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

<div class="dashboard">
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
        <Toggle
          name="mau"
          label="Breakdown"
          options={[
            ["total", "Total"],
            ["services", "By service"],
          ]}
          bind:value={mauView}
        />
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
            Share of monthly active users who logged in to two or more services,
            with its 3-month trailing average.
          </p>
        </div>
      </header>
      <TrendChart
        label="Multi-service usage"
        data={multiRows}
        series={shareSeries}
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
        <label class="picker">
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
      <div class="table-wrap">
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
      </div>
    </section>
  {/if}
</div>
