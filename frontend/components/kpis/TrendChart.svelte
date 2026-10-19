<script lang="ts">
  import { LineChart } from "layerchart";
  import type { ChartRow } from "./activity";

  interface Series {
    key: string;
    color: string;
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
</script>

<figure class="trend" aria-label={label} bind:clientWidth={width}>
  <LineChart
    {data}
    x="date"
    series={series.map((s) => ({
      key: s.key,
      label: s.key,
      value: (d: ChartRow) => d[s.key] as number | null,
      color: s.color,
    }))}
    yDomain={[0, null]}
    yNice
    props={{
      xAxis: { format: formatMonth, ticks: width < 600 ? 3 : 6 },
      yAxis: { format },
      spline: { strokeWidth: 2 },
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
  <ul class="legend">
    {#each series as s (s.key)}
      <li><span class="swatch" style:background={s.color}></span>{s.key}</li>
    {/each}
  </ul>
{/if}

<style>
  .trend {
    height: 20rem;
    margin: 0;
  }
  .legend {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.25rem 1rem;
    margin: 0.75rem 0 0;
    padding: 0;
    list-style: none;
    font-size: var(--font-sm);
    color: var(--gray-5);
  }
  .swatch {
    display: inline-block;
    width: 0.625rem;
    height: 0.625rem;
    border-radius: 2px;
    margin-right: 0.375rem;
  }
</style>
