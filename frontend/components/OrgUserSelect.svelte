<script lang="ts">
  import type { User } from "@/types";

  import Select from "./Select.svelte";
  import UserListItem from "./UserListItem.svelte";

  interface Props {
    organizationSlug: string;
    organizationName: string;
    onChange?: (selection: User) => void;
  }

  let { onChange, organizationName, organizationSlug }: Props = $props();

  let value: User = $state();
  const fetchProps: RequestInit = { credentials: "include" };

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
  name="userid"
  placeholder="Search for a member of {organizationName}..."
  bind:value
  valueAsObject
  valueField="id"
  labelField="name"
  fetch="/fe_api/users/?organization={organizationSlug}"
  {fetchProps}
  fetchCallback={({ results }) => results as User[]}
  fetchDebounceTime={400}
  minQuery={0}
  fetchResetOnBlur={false}
  resetOnBlur={false}
  lazyDropdown={false}
  onChange={handleChange}
>
  {#snippet option(item: User)}
    <UserListItem user={item} />
  {/snippet}

  {#snippet selectionValue({ name, username })}
    {name || username}
  {/snippet}
</Select>
