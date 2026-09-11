<script lang="ts">
  import Audit from './Audit.svelte';

  // Route components receive params; this page has none to use.
  let { params: _params = {} }: { params?: Record<string, string> } = $props();
</script>

<svelte:head><title>Audit log · DartBrains Grader</title></svelte:head>

<div class="page-head">
  <div>
    <p class="eyebrow">Platform admin</p>
    <h1>Audit log</h1>
  </div>
  <span class="muted small">Courses, offerings, staff, publishes, roster imports, exports. Grade changes are only visible to each offering's instructors.</span>
</div>

<Audit scope="platform" />
