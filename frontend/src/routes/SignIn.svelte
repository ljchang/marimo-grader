<script lang="ts">
  import { auth } from '$lib/auth.svelte';
</script>

<main class="page narrow signin">
  <p class="eyebrow">DartBrains Grader</p>
  <h1>Sign in with your Dartmouth NetID</h1>
  <p class="muted">
    Grading, rosters and feedback for marimo assignments. You will be sent to Dartmouth Web
    Authentication and returned here.
  </p>
  <button class="primary" onclick={() => auth.signIn()}>Continue to Dartmouth sign-in</button>
</main>

<style>
  .signin {
    padding-top: 72px;
  }
  h1 {
    margin: 8px 0 10px;
    font-size: 26px;
  }
  p.muted {
    max-width: 52ch;
    margin-bottom: 20px;
  }
</style>
