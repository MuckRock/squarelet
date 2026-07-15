<script lang="ts">
  import type { ComponentProps } from "svelte";
  import Svelecte from "svelecte";

  type SelectProps = ComponentProps<typeof Svelecte>;

  let { value = $bindable(), ...props }: SelectProps = $props();
</script>

<Svelecte
  {...props}
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
