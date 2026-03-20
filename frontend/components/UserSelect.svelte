<script lang="ts">
  import type { User, Selection } from "@/types";

  import Svelecte from "svelecte";
  import UserListItem from "./UserListItem.svelte";
  import plusCircle from "@/icons/plus-circle.svg?raw";

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

<Svelecte
  multiple
  creatable
  name="invitees"
  placeholder="Search users or enter an email..."
  {disabled}
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
  class="svelecte-control user-search"
  --sv-min-height="2rem"
  --sv-disabled-bg="var(--gray-1, #f5f6f7)"
  --sv-border="1px solid var(--gray-3, #99a8b3)"
  --sv-border-radius="0.5rem"
  --sv-placeholder-color="var(--gray-3, #99a8b3)"
  --sv-icon-color="var(--gray-3, #99a8b3)"
  --sv-icon-color-hover="var(--gray-4, #5c717c)"
  --sv-separator-bg="var(--gray-2, #d8dee2)"
  --sv-dropdown-border="1px solid var(--gray-2, #d8dee2)"
  --sv-dropdown-shadow="var(--shadow-2, 0 6px 8px 0px rgba(30 48 56 / 0.1))"
  --sv-dropdown-active-bg="var(--blue-1, #eef3f9)"
  --sv-dropdown-selected-bg="var(--blue-1, #eef3f9)"
  --sv-loader-border="2px solid var(--blue-3, #4294f0)"
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

<style>
  :global(.sv-control--selection) {
    padding: 0 0.25em;
  }

  :global(.svelecte-control.user-search) {
    font-family: var(--font-sans, "Source Sans Pro"), sans-serif;
    font-size: var(--font-md, 1rem);
    font-feature-settings: "ss04" on;
  }

  :global(.svelecte-control.user-search input) {
    font-family: var(--font-sans, "Source Sans Pro"), sans-serif;
    font-size: var(--font-md, 1rem);
  }

  :global(.svelecte-control.user-search .sv-dropdown) {
    border-radius: 0.5rem;
  }

  :global(.svelecte-control.user-search .sv-dropdown .sv-dd-item) {
    font-family: var(--font-sans, "Source Sans Pro"), sans-serif;
    font-size: var(--font-md, 1rem);
    padding: 0.375rem 0.75rem;
  }

  .chip {
    display: inline-flex;
    align-items: center;
    gap: 0.375rem;
    padding: 0.125rem 0.375rem;
    border-radius: 0.25rem;
    font-family: var(--font-sans, "Source Sans Pro"), sans-serif;
    font-size: var(--font-sm, 0.875rem);
    font-weight: 600;
    line-height: normal;
    background: var(--blue-1, #eef3f9);
    border: 1px solid var(--blue-2, #b5ceed);
    color: var(--blue-5, #053775);
  }

  .chip.email {
    background: var(--gray-1, #ebf9f6);
    border: 1px solid var(--gray-2, #9de3d3);
    color: var(--gray-5, #0e4450);
  }

  .chip button {
    all: unset;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1rem;
    height: 1rem;
    border-radius: 50%;
    font-size: var(--font-md, 1rem);
    line-height: 1;
    color: inherit;
    opacity: 0.6;
  }

  .chip button:hover {
    opacity: 1;
    background: rgba(0, 0, 0, 0.1);
  }

  .email-option {
    padding: 0.25rem 0;
    color: var(--gray-5, #233944);
  }
</style>
