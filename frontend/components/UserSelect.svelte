<script lang="ts">
  import type { User, Selection } from "@/types";

  import Select from "./Select.svelte";
  import UserListItem from "./UserListItem.svelte";
  import SelectChip from "./SelectChip.svelte";

  interface Props {
    onChange?: (selections: Selection[]) => void;
  }

  let { onChange }: Props = $props();

  let value: Selection[] = $state([]);
  const fetchProps: RequestInit = { credentials: "include" };

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function fetchCallback(resp: { count: number; results: User[] }): Selection[] {
    return resp.results.map((u) => ({ ...u, type: "user" as const }));
  }

  /** Only allow creating items that look like email addresses.
   *  Svelecte: return true to HIDE the create option, false to SHOW it. */
  function createFilter(query: string): boolean {
    return !emailRegex.test(query);
  }

  /** Transform a created item (email string) into a Selection */
  function createHandler({ inputValue }: { inputValue: string }): Selection {
    return {
      type: "email",
      email: inputValue,
      name: inputValue,
      id: `email:${inputValue}`,
    };
  }

  function handleChange() {
    onChange?.(value);
  }

  /** Svelecte doesn't catch AbortError when it cancels in-flight fetches. */
  function suppressAbortError(e: PromiseRejectionEvent) {
    if (e.reason instanceof DOMException && e.reason.name === "AbortError") {
      e.preventDefault();
    }
  }
</script>

<svelte:window onunhandledrejection={suppressAbortError} />

<Select
  multiple
  creatable
  name="invitees"
  placeholder="Search users or enter an email..."
  bind:value
  valueAsObject
  valueField="id"
  labelField="name"
  fetch="/fe_api/users/?search=[query]"
  {fetchCallback}
  {fetchProps}
  {createFilter}
  {createHandler}
  fetchDebounceTime={400}
  minQuery={3}
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
      <SelectChip type={sel.type}>
        {#snippet content()}
          {sel.type === "email" ? sel.email : sel.name || sel.username}
          <button data-action="deselect" use:bindItem={sel}>&times;</button>
        {/snippet}
      </SelectChip>
    {/each}
  {/snippet}
</Select>

<style>
  .email-option {
    padding: 0.25rem 0;
    color: var(--gray-5, #233944);
  }
</style>
