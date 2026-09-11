<script lang="ts">
  import { auth } from '$lib/auth.svelte';
  import { router } from '$lib/router.svelte';
  import { uiMode } from '$lib/mode.svelte';
  import type { Enrollment } from '$lib/api';

  let { offering = null }: { offering?: Enrollment | null } = $props();

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
        <span class="netid" title={auth.me.display_name}>{auth.me.netid}</span>
        <button class="quiet" onclick={() => auth.signOut()}>Sign out</button>
      {:else if auth.status === 'anonymous'}
        <button class="quiet" onclick={() => auth.signIn()}>Sign in</button>
      {/if}
    </div>
  </div>
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
