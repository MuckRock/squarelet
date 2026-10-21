<script lang="ts">
  import { curveMonotoneX } from "d3-shape";
  import { LineChart } from "layerchart";
  import ChartLegend from "./ChartLegend.svelte";
  import { pinHighlight } from "./highlight";
  import type { ChartRow } from "./activity";

  interface Series {
    key: string;
    color: string;
    width?: number;
  }

  interface Props {
    data: ChartRow[];
    series: Series[];
    format: (value: number) => string;
    label: string;
  }

  let { data, series, format, label }: Props = $props();

  const monthFormat = new Intl.DateTimeFormat("en-US", {
    month: "short",
    year: "numeric",
  });
  const formatMonth = (date: Date) => monthFormat.format(date);
  const formatValue = (value: number | null) =>
    value === null ? "—" : format(value);

  let width = $state(0);
  let highlighted: string | null = $state(null);

  const active = $derived(
    series.some((s) => s.key === highlighted) ? highlighted : null,
  );

  // LayerChart's own highlight also fades the other series' dots and tooltip rows.
  let context: { series: Parameters<typeof pinHighlight>[0] } | undefined =
    $state();
  $effect(() => {
    if (context) pinHighlight(context.series, active);
  });

  function lineProps(s: Series) {
    const base = s.width ?? 2;
    return { strokeWidth: active === s.key ? base + 1 : base };
  }
</script>

<figure class="trend" aria-label={label} bind:clientWidth={width}>
  <LineChart
    bind:context
    {data}
    x="date"
    series={series.map((s) => ({
      key: s.key,
      label: s.key,
      value: (d: ChartRow) => d[s.key] as number | null,
      color: s.color,
      props: lineProps(s),
    }))}
    yDomain={[0, null]}
    yNice
    props={{
      xAxis: { format: formatMonth, ticks: width < 600 ? 3 : 6 },
      yAxis: { format },
      // Monotone so the curve never overshoots past a real month's value.
      spline: { curve: curveMonotoneX },
      tooltip: {
        header: { format: formatMonth },
        item: { format: formatValue },
        // Summing services double-counts anyone on more than one.
        hideTotal: true,
      },
    }}
  />
</figure>
{#if series.length > 1}
  <ChartLegend {series} bind:highlighted />
{/if}

<style>
  .trend {
    height: 20rem;
    margin: 0;
  }
</style>
