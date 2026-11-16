<script lang="ts">
  import { BarChart } from "layerchart";
  import Legend from "./Legend.svelte";
  import {
    longMonth,
    money,
    moneyTick,
    monthTicks,
    shortMonth,
  } from "./format";
  import type { MonthRow } from "./report";

  let { rows }: { rows: MonthRow[] } = $props();

  const NEW = "var(--blue-4)";
  const CHURNED = "var(--red-3)";
  const NET = "var(--gray-5)";

  let width = $state(0);

  const data = $derived(
    rows.map((r) => ({
      month: r.month,
      new: r.new_mrr,
      churned: -r.churned_mrr,
    })),
  );
  // The tooltip's total of the two series is the month's net change.
  const series = [
    {
      key: "new",
      label: "New",
      value: (d: { new: number }) => d.new,
      color: NEW,
    },
    {
      key: "churned",
      label: "Churned",
      value: (d: { churned: number }) => d.churned,
      color: CHURNED,
    },
  ];
  const annotations = $derived(
    rows.map((r) => ({
      type: "point" as const,
      x: r.month,
      y: r.new_mrr - r.churned_mrr,
      r: 3.5,
      fill: NET,
      stroke: "var(--white)",
      strokeWidth: 1.5,
    })),
  );
</script>

<figure
  class="revenue-chart"
  aria-label="New vs churned MRR"
  bind:clientWidth={width}
>
  <BarChart
    {data}
    x="month"
    {series}
    seriesLayout="stackDiverging"
    bandPadding={0.3}
    {annotations}
    props={{
      xAxis: {
        format: shortMonth,
        ticks: monthTicks(width),
      },
      yAxis: { format: moneyTick },
      tooltip: {
        header: { format: longMonth },
        item: { format: money },
      },
    }}
  />
</figure>
<Legend
  series={[
    { key: "New MRR", color: NEW },
    { key: "Churned MRR", color: CHURNED },
    { key: "Net change", color: NET },
  ]}
/>
