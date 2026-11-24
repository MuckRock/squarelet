<script lang="ts" generics="T extends string">
  interface Props {
    name: string;
    label: string;
    options: [T, string][];
    value: T;
  }

  let { name, label, options, value = $bindable() }: Props = $props();
</script>

<div class="toggle" role="radiogroup" aria-label={label}>
  {#each options as [key, text] (key)}
    <label class:active={value === key}>
      <input
        type="radio"
        {name}
        value={key}
        checked={value === key}
        onchange={() => (value = key)}
      />
      {text}
    </label>
  {/each}
</div>
