<script lang="ts">
  import { router } from '$lib/router.svelte';
</script>

<main class="page narrow">
  <p class="eyebrow">404</p>
  <h1>No page at <code>{router.path}</code></h1>
  <p class="muted" style="margin-top:8px"><a href="/">Back to your offerings.</a></p>
</main>
