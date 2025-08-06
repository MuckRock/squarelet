<script lang="ts">
  import type { Organization } from "@/types";

  import Svelecte from "svelecte";

  let selected: Organization | undefined = $state();
  let options: Organization[] = $state([]);

  $inspect(options, selected);

  function onchange(e) {
    console.log(e);
  }
</script>

<form class="container">
  <Svelecte
    name="q"
    placeholder="Search public organizations…"
    bind:value={selected}
    bind:options
    valueAsObject
    labelField="name"
    fetch="/fe_api/organizations/?search=[query]"
    fetchCallback={(resp) => resp.results}
    searchProps={{ skipSort: true }}
  >
    {#snippet selection(selectedOptions: Organization[], bindItem)}
      {#each selectedOptions as org (org.id)}
        <div class="selected">
          {org.name}
          <button data-action="deselect" use:bindItem={org}>&times;</button>
        </div>
      {/each}
    {/snippet}

    {#snippet option(item: Organization)}
      <div class="option">
        {item.name}
      </div>
    {/snippet}
  </Svelecte>
</form>

<style>
  .container {
    display: flex;
    align-items: center;
    justify-content: center;
    max-width: 88ch;
    margin: 2rem auto;
  }
</style>
