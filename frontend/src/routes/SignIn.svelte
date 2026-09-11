<script lang="ts">
  import { auth } from '$lib/auth.svelte';
</script>

<main class="page narrow signin">
  <h1>Sign in with your Dartmouth NetID</h1>
  <p class="muted">
    This is where DartBrains assignments are submitted and graded. Sign-in goes through Dartmouth
    Web Authentication and brings you back here.
  </p>
  <button class="primary" onclick={() => auth.signIn()}>Continue to Dartmouth sign-in</button>
</main>

<style>
  .signin {
    padding-top: 72px;
  }
  h1 {
    margin: 0 0 10px;
  }
  p.muted {
    max-width: 52ch;
    margin-bottom: 20px;
  }
</style>
