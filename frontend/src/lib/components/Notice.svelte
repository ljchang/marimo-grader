<script lang="ts">
  import type { Snippet } from 'svelte';

  let {
    kind = 'info',
    label,
    children,
  }: { kind?: 'info' | 'warn' | 'error'; label?: string; children?: Snippet } = $props();
</script>

<div class="notice {kind}" role={kind === 'error' ? 'alert' : 'status'}>
  {#if label}<span class="label">{label}</span>{/if}
  {@render children?.()}
</div>
