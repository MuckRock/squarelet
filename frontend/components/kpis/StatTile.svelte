<script lang="ts">
  interface Props {
    label: string;
    value: string;
    /** Omit for a figure with nothing to compare against. */
    change?: number | null;
    formatChange?: (change: number) => string;
    detail?: string;
  }

  let {
    label,
    value,
    change,
    formatChange = (n) => `${n > 0 ? "+" : ""}${n.toFixed(1)}%`,
    detail,
  }: Props = $props();

  const direction = $derived(
    change == null || Math.abs(change) < 0.05
      ? "flat"
      : change > 0
        ? "up"
        : "down",
  );
  const changeText = $derived(
    change === null
      ? "No prior month"
      : change === undefined
        ? ""
        : formatChange(change),
  );
</script>

<div class="tile">
  <div class="label">{label}</div>
  <div class="value">{value}</div>
  {#if change === undefined}
    {#if detail}<div class="change">
        <span class="detail">{detail}</span>
      </div>{/if}
  {:else}
    <div class="change {direction}">
      {#if direction === "up"}▲{:else if direction === "down"}▼{/if}
      {changeText}
      <span class="detail">{detail ?? "vs. previous month"}</span>
    </div>
  {/if}
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
