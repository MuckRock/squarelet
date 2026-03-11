<script lang="ts">
  import type { User, Selection } from "@/types";

  import Svelecte from "svelecte";
  import UserListItem from "./UserListItem.svelte";

  interface Props {
    onChange?: (selections: Selection[]) => void;
  }

  let { onChange }: Props = $props();

  let selections: Selection[] = $state([]);
  const fetchProps: RequestInit = { credentials: "include" };

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function fetchCallback(resp: { count: number; results: User[] }): User[] {
    return resp.results;
  }

  /** Only allow creating items that look like email addresses */
  function createFilter(query: string): boolean {
    return emailRegex.test(query);
  }

  /** Transform a created item (email string) into a Selection */
  function createTransform(query: string): Selection {
    return { type: "email", email: query, name: query, id: `email:${query}` };
  }

  function handleChange() {
    onChange?.(selections);
  }
</script>

<Svelecte
  multiple
  creatable
  name="invitees"
  placeholder="Search users or enter an email..."
  bind:value={selections}
  valueAsObject
  labelField="name"
  fetch="/fe_api/users/?search=[query]"
  {fetchCallback}
  {fetchProps}
  {createFilter}
  {createTransform}
  fetchResetOnBlur={false}
  resetOnBlur={false}
  lazyDropdown={false}
  onChange={handleChange}
>
  {#snippet option(item: Selection)}
    {#if item.type === "email"}
      <div class="email-option">
        Invite <strong>{item.email}</strong> by email
      </div>
    {:else}
      <UserListItem user={item} />
    {/if}
  {/snippet}

  {#snippet selection(selectedOptions: Selection[], bindItem)}
    {#each selectedOptions as sel (sel.id)}
      <div class="chip {sel.type}">
        {sel.type === "email" ? sel.email : sel.name || sel.username}
        <button data-action="deselect" use:bindItem={sel}>&times;</button>
      </div>
    {/each}
  {/snippet}
</Svelecte>
