<script lang="ts">
  // Rendered notebook HTML from the worker, shown with every sandbox
  // restriction on: no scripts, no forms, no same-origin access, no popups.
  let {
    src,
    title = 'Rendered notebook',
    height = '420px',
  }: { src: string | null | undefined; title?: string; height?: string } = $props();
</script>

{#if src}
  <iframe class="render" {src} {title} sandbox="allow-scripts" referrerpolicy="no-referrer" style:height></iframe>
{:else}
  <div class="pending" style:height>
    <span class="muted">The notebook is still being rendered. Check back in a minute.</span>
  </div>
{/if}

<style>
  .pending {
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px dashed var(--rule);
    border-radius: var(--radius);
  }
</style>
