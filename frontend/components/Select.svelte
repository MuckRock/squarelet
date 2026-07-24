<script generics="T extends Record<string, any>" lang="ts">
  import type { ComponentProps, Snippet } from "svelte";
  import Svelecte from "svelecte";

  type SelectProps = Omit<ComponentProps<typeof Svelecte>, "fetchCallback"> & {
    fetchCallback: (...args: any) => T[];
    selectionValue: Snippet<[T]>;
  };

  let {
    value = $bindable(),
    valueField,
    selection = _selection,
    selectionValue,
    ...props
  }: SelectProps = $props();
</script>

{#snippet _selection(selectedOptions: T[], bindItem: Function)}
  {#each selectedOptions as selection (selection[valueField])}
    <div class={["chip", { email: selection.type === "email" }]}>
      {@render selectionValue(selection)}
      <button data-action="deselect" use:bindItem={selection}>&times;</button>
    </div>
  {/each}
{/snippet}

<Svelecte
  {...props}
  {selection}
  {valueField}
  bind:value
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
/>

<style>
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

  .email {
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
</style>
