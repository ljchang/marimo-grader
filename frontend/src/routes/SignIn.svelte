<script lang="ts">
  import { onMount } from 'svelte';
  import { auth } from '$lib/auth.svelte';
  import { api, errorMessage, type Health } from '$lib/api';

  let health = $state<Health | null>(null);
  let email = $state('');
  let busy = $state(false);
  let sent = $state<string | null>(null);
  let error = $state<string | null>(null);

  // Single sign-on is the way in. The link form is a fallback for the window
  // before the SP is registered (or an outage), so it only appears when the
  // server says it is both enabled and needed.
  const ssoLive = $derived(health?.auth_mode === 'saml');
  const showLinkForm = $derived(health?.email_login_enabled === true && !ssoLive);

  onMount(async () => {
    try {
      health = await api.health();
    } catch {
      health = null; // Offer the usual button and let the server explain.
    }
  });

  async function requestLink(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = null;
    sent = null;
    try {
      const r = await api.auth.emailLogin(email.trim());
      sent = r.message;
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }
</script>

<main class="page narrow signin">
  <h1>Sign in with your Dartmouth NetID</h1>
  <p class="muted">
    This is where DartBrains assignments are submitted and graded. Sign-in goes through Dartmouth
    Web Authentication and brings you back here.
  </p>
  <button class="primary" onclick={() => auth.signIn()} disabled={health?.auth_mode === 'disabled'}>
    Continue to Dartmouth sign-in
  </button>

  {#if showLinkForm}
    <section class="fallback">
      <h2>Dartmouth sign-in is not available yet</h2>
      <p class="muted">
        While it is being set up, we can email a sign-in link to your Dartmouth address. The link
        works once and expires after seven days.
      </p>

      <form onsubmit={requestLink}>
        <label class="field" for="signin-email"><span>Dartmouth email</span></label>
        <div class="row">
          <input
            id="signin-email"
            type="email"
            bind:value={email}
            required
            autocomplete="email"
            placeholder="netid@dartmouth.edu"
          />
          <button class="primary" type="submit" disabled={busy || email.trim() === ''}>
            {busy ? 'Sending…' : 'Email me a link'}
          </button>
        </div>
      </form>

      {#if sent}<p class="note ok">{sent}</p>{/if}
      {#if error}<p class="note err">{error}</p>{/if}
    </section>
  {/if}
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
  .fallback {
    margin-top: 40px;
    padding-top: 24px;
    border-top: 1px solid var(--line, #e3e6e4);
  }
  .fallback h2 {
    font-size: 1.05rem;
    margin: 0 0 8px;
  }
  .row {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    align-items: center;
  }
  .row input {
    flex: 1;
    min-width: 240px;
  }
  .note {
    max-width: 52ch;
    margin-top: 14px;
  }
  .note.ok {
    color: var(--green, #00693e);
  }
  .note.err {
    color: var(--red, #8a2a00);
  }
</style>
