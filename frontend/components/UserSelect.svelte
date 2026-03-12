<script lang="ts">
  import type { User, Selection } from "@/types";

  import Svelecte from "svelecte";
  import UserListItem from "./UserListItem.svelte";

  interface Props {
    onChange?: (selections: Selection[]) => void;
    onReady?: (api: { clear: () => void }) => void;
    disabled?: boolean;
  }

  let { onChange, onReady, disabled = false }: Props = $props();

  let value: Selection[] = $state([]);

  onReady?.({ clear: () => (value = []) });
  const fetchProps: RequestInit = { credentials: "include" };

  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

  function fetchCallback(resp: { count: number; results: User[] }): User[] {
    return resp.results;
  }

  /** Only allow creating items that look like email addresses.
   *  Svelecte: return true to HIDE the create option, false to SHOW it. */
  function createFilter(query: string): boolean {
    return !emailRegex.test(query);
  }

  /** Transform a created item (email string) into a Selection */
  function createHandler({ inputValue }: { inputValue: string }): Selection {
    return { type: "email", email: inputValue, name: inputValue, id: `email:${inputValue}` };
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

<Svelecte
  multiple
  creatable
  name="invitees"
  placeholder="Search users or enter an email..."
  {disabled}
  bind:value
  valueAsObject
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
      <div class="chip {sel.type}">
        {sel.type === "email" ? sel.email : sel.name || sel.username}
        <button data-action="deselect" use:bindItem={sel}>&times;</button>
      </div>
    {/each}
  {/snippet}
</Svelecte>
