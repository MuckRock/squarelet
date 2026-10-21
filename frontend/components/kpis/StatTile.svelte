<script lang="ts">
  interface Props {
    label: string;
    value: string;
    change: number | null;
    detail?: string;
  }

  let { label, value, change, detail }: Props = $props();

  const direction = $derived(
    change === null || Math.abs(change) < 0.05
      ? "flat"
      : change > 0
        ? "up"
        : "down",
  );
  const changeText = $derived(
    change === null
      ? "No prior month"
      : `${change > 0 ? "+" : ""}${change.toFixed(1)}%`,
  );
</script>

<div class="tile">
  <div class="label">{label}</div>
  <div class="value">{value}</div>
  <div class="change {direction}">
    {#if direction === "up"}▲{:else if direction === "down"}▼{/if}
    {changeText}
    <span class="detail">{detail ?? "vs. previous month"}</span>
  </div>
</div>

<style>
  .tile {
    padding: 1rem 1.25rem;
    border: 1px solid var(--gray-2);
    border-radius: var(--radius);
    background: var(--white);
  }
  .label {
    color: var(--gray-4);
    font-size: var(--font-sm);
    font-weight: var(--font-semibold);
  }
  .value {
    color: var(--gray-5);
    font-size: 2rem;
    font-weight: var(--font-semibold);
    font-variant-numeric: tabular-nums;
    line-height: 1.2;
    margin: 0.25rem 0;
  }
  .change {
    font-size: var(--font-sm);
    font-variant-numeric: tabular-nums;
    color: var(--gray-5);
  }
  .up {
    color: var(--green-4);
  }
  .down {
    color: var(--red-3);
  }
  .detail {
    color: var(--gray-4);
  }
</style>
