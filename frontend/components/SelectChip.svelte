<script lang="ts">
  import type { Snippet } from "svelte";

  let { type, content }: { type?: string; content: Snippet } = $props();
</script>

<div class={["chip", { email: type === "email" }]}>
  {@render content?.()}
</div>

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

  .chip :global(button) {
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

  .chip :global(button:hover) {
    opacity: 1;
    background: rgba(0, 0, 0, 0.1);
  }
</style>
