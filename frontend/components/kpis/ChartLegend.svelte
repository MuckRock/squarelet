<script lang="ts">
  interface Props {
    series: { key: string; color: string }[];
    highlighted?: string | null;
  }

  let { series, highlighted = $bindable(null) }: Props = $props();

  function toggle(key: string) {
    highlighted = highlighted === key ? null : key;
  }
</script>

<ul class="legend">
  {#each series as s (s.key)}
    <li>
      <button
        type="button"
        aria-pressed={highlighted === s.key}
        class:dimmed={highlighted !== null && highlighted !== s.key}
        onclick={() => toggle(s.key)}
        onkeydown={(e) => e.key === "Escape" && (highlighted = null)}
      >
        <span class="swatch" style:background={s.color}></span>{s.key}
      </button>
    </li>
  {/each}
</ul>

<style>
  .legend {
    display: flex;
    flex-wrap: wrap;
    justify-content: center;
    gap: 0.25rem 0.5rem;
    margin: 0.75rem 0 0;
    padding: 0;
    list-style: none;
  }
  button {
    display: inline-flex;
    align-items: center;
    padding: 0.25rem 0.5rem;
    border: 1px solid transparent;
    border-radius: var(--radius);
    background: none;
    font: inherit;
    font-size: var(--font-sm);
    color: var(--gray-5);
    cursor: pointer;
  }
  button:hover {
    background: var(--gray-1);
  }
  button[aria-pressed="true"] {
    border-color: var(--gray-2);
    background: var(--gray-1);
    font-weight: var(--font-semibold);
  }
  button:focus-visible {
    outline: 2px solid var(--primary);
    outline-offset: 1px;
  }
  .dimmed {
    color: var(--gray-3);
  }
  .swatch {
    display: inline-block;
    width: 0.625rem;
    height: 0.625rem;
    border-radius: 2px;
    margin-right: 0.375rem;
  }
</style>
