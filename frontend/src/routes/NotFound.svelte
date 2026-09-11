<script lang="ts">
  import { router } from '$lib/router.svelte';
</script>

<main class="page narrow">
  <h1>There is no page at <code>{router.path}</code></h1>
  <p class="muted" style="margin-top:10px"><a href="/">Back to your courses</a></p>
</main>
