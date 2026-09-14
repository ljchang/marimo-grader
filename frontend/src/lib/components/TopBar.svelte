<script lang="ts">
  import { auth } from '$lib/auth.svelte';
  import { api } from '$lib/api';
  import { router } from '$lib/router.svelte';
  import { uiMode } from '$lib/mode.svelte';
  import type { Enrollment } from '$lib/api';

  let { offering = null }: { offering?: Enrollment | null } = $props();

  // Preferred name lives here rather than in a Settings tab: it is yours and
  // follows you across every course, unlike the per-offering settings.
  let editingName = $state(false);
  let nameDraft = $state('');
  let savingName = $state(false);

  function openNameEditor() {
    nameDraft = auth.me?.display_name ?? '';
    editingName = true;
  }

  async function saveName(e: SubmitEvent) {
    e.preventDefault();
    savingName = true;
    try {
      await api.auth.setPreferredName(nameDraft.trim() || null);
      await auth.load();
      editingName = false;
    } finally {
      savingName = false;
    }
  }

  const staff = $derived(offering ? auth.isStaff(offering.offering_id) : false);
  const instructor = $derived(offering ? auth.isInstructor(offering.offering_id) : false);

  // Accounts that are both admin and teaching staff get an explicit mode switch so the
  // two jobs never share one navigation. Everyone else sees a single mode.
  const dual = $derived(auth.isAdmin && (auth.me?.enrollments.length ?? 0) > 0);
  const mode = $derived(auth.isAdmin && !dual ? 'admin' : dual ? uiMode.value : 'teaching');
  $effect(() => {
    uiMode.followPath(router.path);
  });
  function switchMode(next: 'teaching' | 'admin') {
    uiMode.set(next);
    router.navigate(next === 'admin' ? '/admin' : '/');
  }

  function active(prefix: string, exact = false): boolean {
    return exact ? router.path === prefix : router.path === prefix || router.path.startsWith(prefix + '/');
  }
</script>

<header class="topbar">
  <div class="inner">
    <a class="wordmark" href="/">DartBrains <span>Grader</span></a>

    {#if mode === 'admin'}
      <nav class="ctx" aria-label="Administration">
        <span class="crumb"><span>Platform administration</span></span>
        <a href="/admin" class:active={active('/admin', true)}>Courses &amp; offerings</a>
        <a href="/admin/audit" class:active={active('/admin/audit')}>Audit log</a>
      </nav>
    {:else if offering}
      <nav class="ctx" aria-label="Offering">
        <span class="crumb">
          <span class="mono">{offering.course_slug}</span>
          <span class="sep">/</span>
          <span>{offering.term}</span>
        </span>
        {#if staff}
          <a href="/o/{offering.offering_id}" class:active={active(`/o/${offering.offering_id}`, true) || active(`/o/${offering.offering_id}/grade`) || active(`/o/${offering.offering_id}/students`)}>Triage</a>
          {#if instructor}
            <a href="/o/{offering.offering_id}/assignments" class:active={active(`/o/${offering.offering_id}/assignments`)}>Assignments</a>
            <a href="/o/{offering.offering_id}/roster" class:active={active(`/o/${offering.offering_id}/roster`)}>Roster</a>
          {/if}
        {/if}
        <a href="/me/{offering.offering_id}" class:active={active(`/me/${offering.offering_id}`)}>{staff ? 'Student view' : 'My work'}</a>
      </nav>
    {/if}

    <div class="user">
      {#if dual}
        <div class="mode" role="group" aria-label="Mode">
          <button class="seg" class:on={mode === 'teaching'} onclick={() => switchMode('teaching')}>Teaching</button>
          <button class="seg" class:on={mode === 'admin'} onclick={() => switchMode('admin')}>Admin</button>
        </div>
      {/if}
      {#if auth.signedIn && auth.me}
        <button class="quiet netid" onclick={openNameEditor} title="Change the name you are called">
          {auth.me.display_name || auth.me.netid}
        </button>
        <button class="quiet" onclick={() => auth.signOut()}>Sign out</button>
      {:else if auth.status === 'anonymous'}
        <button class="quiet" onclick={() => auth.signIn()}>Sign in</button>
      {/if}
    </div>
  </div>
{#if editingName}
  <div class="namebar">
    <form onsubmit={saveName}>
      <label for="preferred-name">What would you like to be called?</label>
      <input id="preferred-name" type="text" bind:value={nameDraft} maxlength="200" placeholder={auth.me?.netid} />
      <button class="primary" type="submit" disabled={savingName}>{savingName ? 'Saving…' : 'Save'}</button>
      <button class="quiet" type="button" onclick={() => (editingName = false)}>Cancel</button>
    </form>
    <p class="hint">Shown to your instructor and TAs instead of the name Dartmouth has on file. Leave it empty to go back to that name.</p>
  </div>
{/if}
</header>

<style>
  .mode { display: inline-flex; border: 1px solid var(--rule); border-radius: 6px; overflow: hidden; }
  .seg { font: inherit; font-size: 0.85rem; padding: 0.25rem 0.7rem; border: 0; background: transparent; color: var(--muted); cursor: pointer; }
  .seg.on { background: var(--accent); color: var(--accent-ink, #fff); }
  .seg:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
  .topbar {
    height: var(--topbar-h);
    border-bottom: 1px solid var(--rule);
    background: var(--paper);
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .inner {
    height: 100%;
    max-width: 1280px;
    margin: 0 auto;
    padding: 0 20px;
    display: flex;
    align-items: center;
    gap: 24px;
  }
  .wordmark {
    color: var(--ink);
    font-weight: 600;
    letter-spacing: -0.01em;
    white-space: nowrap;
  }
  .wordmark span {
    color: var(--accent);
  }
  .wordmark:hover {
    text-decoration: none;
  }
  .ctx {
    display: flex;
    align-items: center;
    gap: 14px;
    min-width: 0;
    overflow-x: auto;
    font-size: 13px;
  }
  .crumb {
    color: var(--muted);
    white-space: nowrap;
  }
  .sep {
    margin: 0 4px;
    opacity: 0.6;
  }
  .ctx a {
    color: var(--ink);
    padding: 4px 0;
    border-bottom: 2px solid transparent;
    white-space: nowrap;
  }
  .ctx a:hover {
    text-decoration: none;
    border-color: var(--rule);
  }
  .ctx a.active {
    border-color: var(--accent);
  }
  .user {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 13px;
    white-space: nowrap;
  }
  .namebar {
    border-top: 1px solid var(--line, #e3e6e4);
    padding: 10px 16px;
  }
  .namebar form {
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
  }
  .namebar input {
    min-width: 220px;
  }
  .namebar .hint {
    margin: 6px 0 0;
    color: var(--muted);
    font-size: 0.85em;
  }
  .netid {
    font-family: var(--mono);
    color: var(--muted);
  }
  @media (max-width: 640px) {
    .inner {
      gap: 12px;
      padding: 0 16px;
    }
    .crumb {
      display: none;
    }
  }
</style>
