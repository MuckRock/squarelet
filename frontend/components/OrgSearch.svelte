<script lang="ts">
  import type { Organization } from "@/types";

  import Svelecte from "svelecte";
  import TeamListItem from "./TeamListItem.svelte";

  let selected: Organization | undefined = $state();

  const fetchProps: RequestInit = { credentials: "include" };

  function onchange(e) {
    console.log(e);
  }
</script>

<form class="container">
  <Svelecte
    name="q"
    placeholder="Search public organizations…"
    bind:value={selected}
    valueAsObject
    labelField="name"
    fetch="/fe_api/organizations/?individual=false&private=false&search=[query]"
    fetchCallback={(resp) => resp.results}
    fetchResetOnBlur={false}
    resetOnBlur={false}
    lazyDropdown={false}
    {fetchProps}
    searchProps={{ skipSort: true }}
    {onchange}
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
      <TeamListItem organization={item} />
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
