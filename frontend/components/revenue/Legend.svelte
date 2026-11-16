<script lang="ts">
  let { series }: { series: { key: string; color: string }[] } = $props();
</script>

<ul class="legend">
  {#each series as s (s.key)}
    <li><span class="swatch" style:background={s.color}></span>{s.key}</li>
  {/each}
</ul>

<style>
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
