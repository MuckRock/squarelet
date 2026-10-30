<script lang="ts">
  import type { User, Selection } from "@/types";

  import Select from "./Select.svelte";
  import UserListItem from "./UserListItem.svelte";

  interface Props {
    onChange?: (selections: Selection[]) => void;
  }

  let { onChange }: Props = $props();

  let value: Selection[] = $state([]);
  const fetchProps: RequestInit = { credentials: "include" };

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  let query = "";
  let searchedQuery: string | null = $state(null);
  let searchEmpty = $state(false);

  // Svelecte does not expose the input value, so we have to work around it
  function trackQuery(e: Event) {
    const target = e.target as HTMLInputElement;
    if (target.matches("input.sv-input--text")) {
      query = target.value.trim();
    }
  }

  function fetchCallback(resp: {
    count: number;
    results: User[];
  }): Selection[] {
    searchedQuery = query;
    searchEmpty = resp.results.length === 0;
    return resp.results.map((u) => ({ ...u, type: "user" as const }));
  }

  /** Offer an email invite if the search doesn't return a match for an existing user.
   *  Svelecte: return true to HIDE the create option, false to SHOW it. */
  function createFilter(input: string): boolean {
    const email = input.trim();
    return !(emailRegex.test(email) && searchedQuery === email && searchEmpty);
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

<div oninput={trackQuery} style:display="contents">
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
    searchProps={{ disabled: true }}
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

    {#snippet selectionValue(sel)}
      {sel.type === "email" ? sel.email : sel.name || sel.username}
    {/snippet}
  </Select>
</div>

<style>
  .email-option {
    padding: 0.25rem 0;
    color: var(--gray-5, #233944);
  }
</style>
