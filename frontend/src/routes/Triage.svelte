<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import {
    api,
    errorMessage,
    type Assignment,
    type Grid,
    type Question,
    type Triage,
  } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import { router } from '$lib/router.svelte';
  import { subscribeEvents, debounce, type StreamState } from '$lib/events';
  import { fmtDateTime, fmtPercent, fmtRelative } from '$lib/format';
  import type { Params } from '$lib/router.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import StateChip from '$lib/components/StateChip.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  let triage = $state<Triage | null>(null);
  let grid = $state<Grid | null>(null);
  let assignments = $state<Assignment[]>([]);
  let selectedAssignment = $state<string>(router.query.get('assignment') ?? '');
  let error = $state<string | null>(null);
  let stream = $state<StreamState>('closed');
  let refreshedAt = $state<number>(Date.now());

  const questionsById = $derived.by(() => {
    const m = new Map<string, Question & { assignment: Assignment }>();
    for (const a of assignments) for (const q of a.questions) m.set(q.id, { ...q, assignment: a });
    return m;
  });

  const selected = $derived(assignments.find((a) => a.id === selectedAssignment) ?? null);

  const columns = $derived.by((): Question[] => {
    if (selected) return [...selected.questions].sort((a, b) => a.order - b.order);
    // No assignment chosen: derive columns from whatever the grid returned.
    const seen = new Map<string, Question>();
    for (const s of grid?.students ?? []) {
      for (const qid of Object.keys(s.cells)) {
        const q = questionsById.get(qid);
        if (q && !seen.has(qid)) seen.set(qid, q);
      }
    }
    return [...seen.values()].sort((a, b) => a.order - b.order);
  });

  const totals = $derived.by(() => {
    const t = { none: 0, checking: 0, submitted: 0, graded: 0 };
    for (const s of grid?.students ?? []) for (const c of Object.values(s.cells)) t[c.state] += 1;
    return t;
  });

  async function loadTriage() {
    try {
      triage = await api.grading.triage(offeringId);
      refreshedAt = Date.now();
    } catch (err) {
      error = errorMessage(err);
    }
  }

  async function loadGrid() {
    try {
      grid = await api.grading.grid(offeringId, selectedAssignment || undefined);
    } catch (err) {
      error = errorMessage(err);
    }
  }

  async function loadAssignments() {
    try {
      assignments = await api.offerings.assignments(offeringId);
      if (!selectedAssignment && assignments.length > 0) {
        selectedAssignment = assignments[0]?.id ?? '';
      }
    } catch (err) {
      error = errorMessage(err);
    }
  }

  const refresh = debounce(() => {
    error = null;
    void loadTriage();
    void loadGrid();
  }, 500);

  let unsubscribe: (() => void) | null = null;

  onMount(async () => {
    await loadAssignments();
    await Promise.all([loadTriage(), loadGrid()]);
    unsubscribe = subscribeEvents(offeringId, () => refresh(), (s) => (stream = s));
  });

  onDestroy(() => {
    refresh.cancel();
    unsubscribe?.();
  });

  function onAssignmentChange() {
    grid = null;
    const url = new URL(window.location.href);
    if (selectedAssignment) url.searchParams.set('assignment', selectedAssignment);
    else url.searchParams.delete('assignment');
    history.replaceState(null, '', url);
    void loadGrid();
  }

  function questionLabel(questionId: string, qid?: string): string {
    return questionsById.get(questionId)?.qid ?? qid ?? questionId;
  }

  function questionTitle(questionId: string): string {
    const q = questionsById.get(questionId);
    return q ? `${q.assignment.title} · ${q.title}` : '';
  }
</script>

<div class="page-head">
  <div>
    <p class="eyebrow">{enrollment?.role ?? 'staff'} · {enrollment?.term ?? ''}</p>
    <h1>{enrollment?.title ?? offeringId}</h1>
  </div>
  <div class="meta">
    <span class="live {stream}">{stream === 'open' ? 'live' : stream}</span>
    <span>refreshed {fmtRelative(new Date(refreshedAt).toISOString())}</span>
    <button class="quiet" onclick={() => refresh()}>Refresh</button>
  </div>
</div>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}

{#if triage === null}
  <Loading label="Loading triage" />
{:else}
  <div class="grid-2 triage">
    <section class="block">
      <div class="block-head">
        <h2>Awaiting manual grading <span class="count" class:hot={triage.awaiting_manual.length > 0}>{triage.awaiting_manual.reduce((n, a) => n + a.count, 0)}</span></h2>
        <span class="muted small">oldest first</span>
      </div>
      {#if triage.awaiting_manual.length === 0}
        <p class="empty">Nothing waiting.</p>
      {:else}
        <table class="data">
          <thead><tr><th>Question</th><th class="num">Waiting</th><th>Oldest</th><th></th></tr></thead>
          <tbody>
            {#each triage.awaiting_manual as a (a.question_id)}
              <tr>
                <td class="wrap"><span class="mono">{questionLabel(a.question_id, a.qid)}</span><span class="sub">{a.title ?? questionTitle(a.question_id)}</span></td>
                <td class="num">{a.count}</td>
                <td title={fmtDateTime(a.oldest_submitted_at)}>{fmtRelative(a.oldest_submitted_at)}</td>
                <td><a class="btn primary small" href="/o/{offeringId}/grade/{a.question_id}">Grade</a></td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section class="block">
      <div class="block-head">
        <h2>Inactive students <span class="count" class:warn={triage.inactive_students.length > 0}>{triage.inactive_students.length}</span></h2>
        <span class="muted small">no activity in 7 days while an assignment is open</span>
      </div>
      {#if triage.inactive_students.length === 0}
        <p class="empty">Everyone has been active.</p>
      {:else}
        <table class="data">
          <thead><tr><th>Student</th><th>Section</th><th>Last activity</th></tr></thead>
          <tbody>
            {#each triage.inactive_students as s (s.netid)}
              <tr>
                <td><a href="/o/{offeringId}/students/{s.netid}">{s.display_name ?? s.netid}</a><span class="sub mono">{s.netid}</span></td>
                <td>{s.section ?? '—'}</td>
                <td title={fmtDateTime(s.last_activity)}>{s.last_activity ? fmtRelative(s.last_activity) : 'never'}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section class="block">
      <div class="block-head">
        <h2>Failing checks <span class="count" class:warn={triage.failing_checks.length > 0}>{triage.failing_checks.length}</span></h2>
        <span class="muted small">more than a third of the class, last 48 h</span>
      </div>
      {#if triage.failing_checks.length === 0}
        <p class="empty">No check is failing broadly.</p>
      {:else}
        <table class="data">
          <thead><tr><th>Question</th><th>Check</th><th class="num">Fail rate</th><th class="num">n</th></tr></thead>
          <tbody>
            {#each triage.failing_checks as c (c.qid + c.check_key)}
              <tr>
                <td class="mono">{c.qid}</td>
                <td class="wrap"><span class="mono">{c.check_key}</span>{#if c.message}<span class="sub">{c.message}</span>{/if}</td>
                <td class="num">{fmtPercent(c.fail_rate)}</td>
                <td class="num">{c.n}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>

    <section class="block">
      <div class="block-head">
        <h2>Grader failures <span class="count" class:warn={triage.grader_failures.length > 0}>{triage.grader_failures.length}</span></h2>
        <span class="muted small">timeouts and crashes needing a look</span>
      </div>
      {#if triage.grader_failures.length === 0}
        <p class="empty">The autograder is healthy.</p>
      {:else}
        <table class="data">
          <thead><tr><th>Student</th><th>Question</th><th>Error</th><th>When</th></tr></thead>
          <tbody>
            {#each triage.grader_failures as f (f.submission_id)}
              <tr>
                <td><a href="/o/{offeringId}/students/{f.netid}">{f.netid}</a></td>
                <td class="mono">{questionLabel(f.question_id, f.qid)}</td>
                <td class="wrap"><code>{f.error ?? 'unknown'}</code></td>
                <td title={fmtDateTime(f.submitted_at)}>{fmtRelative(f.submitted_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      {/if}
    </section>
  </div>
{/if}

<section class="block roster">
  <div class="block-head">
    <h2>Roster grid <span class="count">{grid?.students.length ?? 0}</span></h2>
    <div class="row">
      <span class="muted small">
        <StateChip state="graded" /> {totals.graded}
        <StateChip state="submitted" /> {totals.submitted}
        <StateChip state="checking" /> {totals.checking}
        <StateChip state="none" /> {totals.none}
      </span>
      <label class="field inline" style="margin:0">
        <span>Assignment</span>
        <select bind:value={selectedAssignment} onchange={onAssignmentChange} style="width:auto">
          <option value="">All</option>
          {#each assignments as a (a.id)}
            <option value={a.id}>{a.title}</option>
          {/each}
        </select>
      </label>
    </div>
  </div>

  {#if grid === null}
    <Loading label="Loading grid" />
  {:else if grid.students.length === 0}
    <p class="empty">No students on the roster yet. <a href="/o/{offeringId}/roster">Import one.</a></p>
  {:else}
    <div class="tablewrap">
      <table class="data grid">
        <thead>
          <tr>
            <th>Student</th>
            <th>Section</th>
            <th>Activity</th>
            {#each columns as q (q.id)}
              <th class="q" title={q.title}>
                {#if q.grading_mode !== 'auto'}
                  <a href="/o/{offeringId}/grade/{q.id}">{q.qid}</a>
                {:else}
                  {q.qid}
                {/if}
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each grid.students as s (s.netid)}
            <tr>
              <td><a href="/o/{offeringId}/students/{s.netid}">{s.display_name || s.netid}</a><span class="sub mono">{s.netid}</span></td>
              <td>{s.section ?? '—'}</td>
              <td class="muted" title={fmtDateTime(s.last_activity)}>{s.last_activity ? fmtRelative(s.last_activity) : '—'}</td>
              {#each columns as q (q.id)}
                {@const c = s.cells[q.id]}
                <td class="cell">
                  {#if c}
                    <StateChip state={c.state} points={c.points} max={c.max} />
                  {:else}
                    <StateChip state="none" />
                  {/if}
                </td>
              {/each}
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<style>
  .triage {
    margin-bottom: 8px;
    grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  }
  .btn.small {
    padding: 4px 9px;
    font-size: 12px;
  }
  table.grid th.q {
    text-align: center;
    font-family: var(--mono);
    text-transform: none;
    letter-spacing: 0;
  }
  table.grid td.cell {
    text-align: center;
  }
  table.grid td:first-child {
    position: sticky;
    left: 0;
    background: var(--paper);
  }
  table.grid tbody tr:hover td:first-child {
    background: var(--surface);
  }
</style>
