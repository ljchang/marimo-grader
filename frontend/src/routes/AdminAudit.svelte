<script lang="ts">
  import Audit from './Audit.svelte';

  // Route components receive params; this page has none to use.
  let { params: _params = {} }: { params?: Record<string, string> } = $props();
</script>

<svelte:head><title>Audit log · DartBrains Grader</title></svelte:head>

<div class="page-head">
  <div>
    <h1>Audit log</h1>
    <p class="eyebrow">Courses, offerings, staff, publishes, roster imports, and exports. Grade changes are only visible to each course's instructors.</p>
  </div>
</div>

<Audit scope="platform" />
