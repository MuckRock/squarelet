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

  interface Props {
    /** Each segment's rows for the same months, keyed by segment. */
    bySegment: {
      key: string;
      label: string;
      color: string;
      rows: MonthRow[];
    }[];
  }

  let { bySegment }: Props = $props();

  let width = $state(0);

  const data = $derived(
    (bySegment[0]?.rows ?? []).map((row, i) => ({
      month: row.month,
      ...Object.fromEntries(bySegment.map((s) => [s.key, s.rows[i].mrr_end])),
    })),
  );
  const series = $derived(
    bySegment.map((s) => ({
      key: s.key,
      label: s.label,
      value: (d: Record<string, number>) => d[s.key],
      color: s.color,
    })),
  );
</script>

<figure
  class="revenue-chart tall"
  aria-label="MRR by plan"
  bind:clientWidth={width}
>
  <BarChart
    {data}
    x="month"
    {series}
    seriesLayout="stack"
    bandPadding={0.3}
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
<Legend series={bySegment.map((s) => ({ key: s.label, color: s.color }))} />
