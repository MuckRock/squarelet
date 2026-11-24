<script lang="ts">
  import { BarChart, Circle } from "layerchart";
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
  const NET_FILL = "var(--white)";
  const NET_OUTLINE = "var(--gray-5)";

  let width = $state(0);

  const data = $derived(
    rows.map((r) => ({
      month: r.month,
      new: r.new_mrr,
      // 0 - x rather than -x: a month with no churn would show as "-$0".
      churned: 0 - r.churned_mrr,
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
  const net = $derived(
    rows.map((r) => ({ month: r.month, value: r.new_mrr - r.churned_mrr })),
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
    props={{
      bars: { strokeWidth: 0 },
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
  >
    <!-- LayerChart's annotation points treat 0 as missing and drop to the
         chart's floor, so the dots are placed from the scales here. -->
    {#snippet aboveMarks({ context })}
      {#each net as point (point.month)}
        <Circle
          cx={context.xScale(point.month) + context.xScale.bandwidth() / 2}
          cy={context.yScale(point.value)}
          r={4}
          fill={NET_FILL}
          stroke={NET_OUTLINE}
          strokeWidth={1.5}
          class="revenue-net-dot"
        />
      {/each}
    {/snippet}
  </BarChart>
</figure>
<Legend
  series={[
    { key: "New MRR", color: NEW },
    { key: "Churned MRR", color: CHURNED },
    { key: "Net change", color: NET_FILL, outline: NET_OUTLINE, round: true },
  ]}
/>
