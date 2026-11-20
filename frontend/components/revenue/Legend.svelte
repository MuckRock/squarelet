<script lang="ts">
  interface Entry {
    key: string;
    color: string;
    outline?: string;
    round?: boolean;
  }

  let { series }: { series: Entry[] } = $props();
</script>

<ul class="legend">
  {#each series as s (s.key)}
    <li>
      <span
        class="swatch"
        class:round={s.round}
        style:background={s.color}
        style:box-shadow={s.outline ? `inset 0 0 0 1.5px ${s.outline}` : null}
      ></span>{s.key}
    </li>
  {/each}
</ul>

<style>
  .round {
    border-radius: 50%;
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
</style>
