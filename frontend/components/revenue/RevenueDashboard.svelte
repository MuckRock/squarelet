<script lang="ts">
  import StatTile from "../kpis/StatTile.svelte";
  import Toggle from "../kpis/Toggle.svelte";
  import TrendChart from "../kpis/TrendChart.svelte";
  import FlowChart from "./FlowChart.svelte";
  import MrrByPlanChart from "./MrrByPlanChart.svelte";
  import {
    ALL,
    type Report,
    type Window,
    monthDate,
    segmentMonths,
    trailingChurn,
    visibleMonths,
    windowKpis,
  } from "./report";
  import {
    integer,
    longMonth,
    money,
    monthName,
    percent,
    signedInteger,
  } from "./format";

  let { report }: { report: Report } = $props();

  // Fixed order, matching the Users dashboard, so a plan keeps its color.
  const PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"];

  let windowKey: "12" | "3" = $state("12");
  const span = $derived(Number(windowKey) as Window);

  const kpis = $derived(windowKpis(report, span));
  const shown = $derived(new Set(visibleMonths(report, span)));
  const charted = (rows: { month: string; partial: boolean }[]) =>
    rows.filter((r) => shown.has(r.month) && !r.partial);

  const all = $derived(segmentMonths(report));
  const bySegment = $derived(
    report.segments.map(([key, label], i) => ({
      key,
      label,
      color: PALETTE[i % PALETTE.length],
      rows: charted(segmentMonths(report, key)),
    })),
  );

  const CUSTOMER = "Customer churn";
  const CUSTOMER_AVG = "Customer churn, 3-mo avg";
  const MRR = "MRR churn";
  const MRR_AVG = "MRR churn, 3-mo avg";
  const churnSeries = [
    { key: CUSTOMER, color: "#9dc0eb", width: 1.5 },
    { key: CUSTOMER_AVG, color: PALETTE[0], width: 2.5 },
    { key: MRR, color: "#f5b49a", width: 1.5 },
    { key: MRR_AVG, color: PALETTE[1], width: 2.5 },
  ];
  const churnRows = $derived.by(() => {
    const full = all.filter((r) => !r.partial);
    const trailing = trailingChurn(full);
    return full
      .map((r, i) => ({ row: r, avg: trailing[i] }))
      .filter(({ row }) => shown.has(row.month))
      .map(({ row, avg }) => ({
        date: monthDate(row.month),
        [CUSTOMER]: row.logo_churn,
        [CUSTOMER_AVG]: avg?.logo ?? null,
        [MRR]: row.mrr_churn,
        [MRR_AVG]: avg?.mrr ?? null,
      }));
  });

  let segment = $state(ALL);
  const tableRows = $derived(
    segmentMonths(report, segment)
      .filter((r) => shown.has(r.month))
      .reverse(),
  );

  const pendingAll = $derived(report.pending.find((p) => p.segment === ALL));
  const pendingRows = $derived(report.pending.filter((p) => p.segment !== ALL));

  const day = (month: string) =>
    monthName(month, { month: "short", day: "numeric", year: "numeric" });
  const range = $derived(
    kpis
      ? `${longMonth(kpis.first.month)} – ${longMonth(kpis.last.month)}`
      : "",
  );
</script>

<div class="dashboard">
  {#if !kpis}
    <p class="empty">No complete months of subscription data yet.</p>
  {:else}
    <section class="card-header" aria-label="Summary">
      <Toggle
        name="window"
        label="Time window"
        options={[
          ["12", "Last 12 months"],
          ["3", "Last 3 months"],
        ]}
        bind:value={windowKey}
      />
      <p class="summary">
        Since {day(kpis.first.month)}, MRR has gone from
        <b>{money(kpis.first.mrr_start)}</b> to
        <b>{money(kpis.now.mrr_end)}</b> a month, and paying subscriptions from
        <b>{integer(kpis.first.subs_start)}</b> to
        <b>{integer(kpis.now.subs_end)}</b>.
      </p>
    </section>

    <section class="tile-grid" aria-label="Headline figures">
      <StatTile
        label="MRR now"
        value={money(kpis.now.mrr_end)}
        change={kpis.mrrChange === null ? null : kpis.mrrChange * 100}
        detail={`since ${day(kpis.first.month)}`}
      />
      <StatTile
        label="Paying subscriptions"
        value={integer(kpis.now.subs_end)}
        change={kpis.subsChange}
        formatChange={signedInteger}
        detail={`since ${day(kpis.first.month)}`}
      />
      <StatTile
        label="Monthly customer churn"
        value={percent(kpis.churn.logo)}
        detail={`Average, ${range}`}
      />
      <StatTile
        label="Monthly MRR churn"
        value={percent(kpis.churn.mrr)}
        detail={`Average, ${range}`}
      />
      <StatTile
        label="Set to cancel"
        value={money(pendingAll?.mrr ?? 0)}
        detail={`MRR across ${integer(pendingAll?.subs ?? 0)} subscriptions ending at period end`}
      />
    </section>

    <section class="card">
      <header>
        <div>
          <h3>MRR by plan</h3>
          <p>
            Month-end MRR over complete months. Annual plans count at a twelfth
            of their price.
          </p>
        </div>
      </header>
      <MrrByPlanChart {bySegment} />
    </section>

    <div class="card-grid">
      <section class="card">
        <header>
          <div>
            <h3>New vs churned MRR</h3>
            <p>
              All paid plans. Bars above the line are MRR from new
              subscriptions, bars below are MRR from subscriptions that ended.
              The dot is the net change.
            </p>
          </div>
        </header>
        <FlowChart rows={charted(all)} />
      </section>

      <section class="card">
        <header>
          <div>
            <h3>Churn rate</h3>
            <p>
              All paid plans. Customer churn is the share of subscriptions lost;
              MRR churn weighs them by what they paid. Bold lines are 3-month
              trailing averages.
            </p>
          </div>
        </header>
        <TrendChart
          label="Churn rate"
          data={churnRows}
          series={churnSeries}
          format={(n) => percent(n)}
        />
      </section>
    </div>

    <section class="card">
      <header>
        <div>
          <h3>Monthly detail</h3>
        </div>
        <label class="picker">
          Plan
          <select bind:value={segment}>
            <option value={ALL}>All plans</option>
            {#each report.segments as [key, label] (key)}
              <option value={key}>{label}</option>
            {/each}
          </select>
        </label>
      </header>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Month</th>
              <th scope="col">Subs at start</th>
              <th scope="col">New</th>
              <th scope="col">Churned</th>
              <th scope="col">Subs at end</th>
              <th scope="col">MRR at start</th>
              <th scope="col">New MRR</th>
              <th scope="col">Churned MRR</th>
              <th scope="col">MRR at end</th>
              <th scope="col">Customer churn</th>
              <th scope="col">MRR churn</th>
            </tr>
          </thead>
          <tbody>
            {#each tableRows as row (row.month)}
              <tr class:partial={row.partial}>
                <th scope="row"
                  >{longMonth(row.month)}{row.partial ? " (to date)" : ""}</th
                >
                <td>{integer(row.subs_start)}</td>
                <td>{integer(row.new)}</td>
                <td>{integer(row.churned)}</td>
                <td>{integer(row.subs_end)}</td>
                <td>{money(row.mrr_start)}</td>
                <td>{money(row.new_mrr)}</td>
                <td>{money(row.churned_mrr)}</td>
                <td>{money(row.mrr_end)}</td>
                <td>{percent(row.logo_churn)}</td>
                <td>{percent(row.mrr_churn)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    </section>

    <div class="card-grid">
      <section class="card">
        <header>
          <div>
            <h3>Set to cancel</h3>
            <p>
              Active subscriptions that will end at the close of their current
              period unless the customer changes their mind.
            </p>
          </div>
        </header>
        <div class="table-wrap">
          <table class="pending">
            <thead>
              <tr>
                <th scope="col">Plan</th>
                <th scope="col">Subscriptions</th>
                <th scope="col">MRR</th>
              </tr>
            </thead>
            <tbody>
              {#each pendingRows as row (row.segment)}
                <tr>
                  <th scope="row">{row.segment_label}</th>
                  <td>{integer(row.subs)}</td>
                  <td>{money(row.mrr)}</td>
                </tr>
              {/each}
            </tbody>
            {#if pendingAll}
              <tfoot>
                <tr>
                  <th scope="row">All plans</th>
                  <td>{integer(pendingAll.subs)}</td>
                  <td>{money(pendingAll.mrr)}</td>
                </tr>
              </tfoot>
            {/if}
          </table>
        </div>
      </section>

      <section class="card">
        <header><h3>How these are counted</h3></header>
        <dl class="definitions">
          <div>
            <dt>MRR</dt>
            <dd>
              Monthly recurring revenue: each live subscription's list price at
              its current quantity, with annual plans divided by 12. Discounts
              aren't applied.
            </dd>
          </div>
          <div>
            <dt>Customer churn</dt>
            <dd>
              Subscriptions that ended in the month, divided by those live at
              its start. Every customer counts as one.
            </dd>
          </div>
          <div>
            <dt>MRR churn</dt>
            <dd>
              MRR of the subscriptions that ended, divided by MRR at the start
              of the month.
            </dd>
          </div>
          <div>
            <dt>Churned</dt>
            <dd>
              Dated by when the subscription actually ended, not when the
              customer clicked cancel.
            </dd>
          </div>
          <div>
            <dt>Left out</dt>
            <dd>
              Free subscriptions, ones whose first payment never went through,
              and Stripe prices that belong to no Squarelet plan, such as
              recurring donations.
            </dd>
          </div>
          <div>
            <dt>Sunlight</dt>
            <dd>
              All Sunlight Research Center plans, including the Election
              Accountability Cohort.
            </dd>
          </div>
          <div>
            <dt>Seat changes</dt>
            <dd>
              Every month uses a subscription's current price and quantity, so
              seat changes during the year aren't reflected.
            </dd>
          </div>
        </dl>
      </section>
    </div>
  {/if}
</div>

<style>
  .card-header {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 0.75rem;
  }
  .summary {
    margin: 0;
    max-width: 72ch;
    color: var(--gray-5);
    line-height: 1.5;
  }
</style>
