<script lang="ts">
  import type { Organization } from "@/types";

  import Select from "./Select.svelte";
  import TeamListItem from "./TeamListItem.svelte";
  import SelectChip from "./SelectChip.svelte";

  let {
    name = "q",
    onChange = onChangeDefault,
  }: { name?: string; onChange?: (org: Organization) => void } = $props();

  const fetchProps: RequestInit = { credentials: "include" };

  function onChangeDefault(org: Organization) {
    const url = new URL(`/organizations/${org.slug}/`, window.location.href);
    window.location = url;
  }
</script>

<Select
  {name}
  placeholder="Search public organizations…"
  valueAsObject
  valueField="slug"
  labelField="name"
  fetch="/fe_api/organizations/?individual=false&search=[query]"
  fetchCallback={(resp) => resp.results}
  fetchResetOnBlur={false}
  resetOnBlur={false}
  lazyDropdown={false}
  {fetchProps}
  searchProps={{ skipSort: true }}
  {onChange}
>
  {#snippet selection(selectedOptions: Organization[], bindItem)}
    {#each selectedOptions as org (org.id)}
      <SelectChip>
        {#snippet content()}
          {org.name}
          <button data-action="deselect" use:bindItem={org}>&times;</button>
        {/snippet}
      </SelectChip>
    {/each}
  {/snippet}

  {#snippet option(item: Organization)}
    <TeamListItem organization={item} />
  {/snippet}
</Select>
