<script lang="ts">
  let { label = 'Loading' }: { label?: string } = $props();
</script>

<p class="muted small loading" aria-live="polite">{label}…</p>

<style>
  .loading {
    padding: 12px 0;
  }
</style>
