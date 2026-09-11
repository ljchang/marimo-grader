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
  let retrying = $state<Set<string>>(new Set());

  const questionsById = $derived.by(() => {
    const m = new Map<string, Question & { assignment: Assignment }>();
    for (const a of assignments) for (const q of a.questions) m.set(q.id, { ...q, assignment: a });
    return m;
  });

  const selected = $derived(assignments.find((a) => a.id === selectedAssignment) ?? null);

  const columns = $derived.by((): Question[] => {
    if (selected) return [...selected.questions].sort((a, b) => a.order - b.order);
    const seen = new Map<string, Question>();
    for (const s of grid?.students ?? []) {
      for (const qid of Object.keys(s.cells)) {
        const q = questionsById.get(qid);
        if (q && !seen.has(qid)) seen.set(qid, q);
      }
    }
    return [...seen.values()].sort((a, b) => a.order - b.order);
  });

  type Tally = { graded: number; submitted: number; failed: number; none: number; checking: number };
  /** Per-column tallies for the footer row. */
  const columnTotals = $derived.by(() => {
    const out = new Map<string, Tally>();
    for (const q of columns) out.set(q.id, { graded: 0, submitted: 0, failed: 0, none: 0, checking: 0 });
    for (const s of grid?.students ?? []) {
      for (const q of columns) {
        const t = out.get(q.id)!;
        const state = (s.cells[q.id]?.state ?? 'none') as keyof Tally;
        if (state in t) t[state] += 1;
        else t.none += 1;
      }
    }
    return out;
  });

  const waitingTotal = $derived(triage?.awaiting_manual.reduce((n, a) => n + a.count, 0) ?? 0);
  const attentionCount = $derived(
    triage
      ? (waitingTotal > 0 ? 1 : 0) +
        (triage.inactive_students.length > 0 ? 1 : 0) +
        triage.failing_checks.length +
        (triage.grader_failures.length > 0 ? 1 : 0)
      : 0,
  );

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

  function selectAssignment(id: string) {
    if (id === selectedAssignment) return;
    selectedAssignment = id;
    grid = null;
    const url = new URL(window.location.href);
    if (id) url.searchParams.set('assignment', id);
    else url.searchParams.delete('assignment');
    history.replaceState(null, '', url);
    void loadGrid();
  }

  async function retry(submissionId: string) {
    retrying = new Set([...retrying, submissionId]);
    try {
      await api.grading.retry(submissionId);
      await loadTriage();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      const next = new Set(retrying);
      next.delete(submissionId);
      retrying = next;
    }
  }

  function questionLabel(questionId: string, qid?: string): string {
    return questionsById.get(questionId)?.qid ?? qid ?? questionId;
  }

  function fmtNum(n: number | null | undefined): string {
    if (n === null || n === undefined) return '?';
    return Number.isInteger(n) ? String(n) : n.toFixed(1);
  }

  function cellText(c: { state: string; points?: number | null; max?: number | null } | undefined): string {
    if (!c || c.state === 'none') return '—';
    if (c.state === 'graded') return `${fmtNum(c.points)}/${fmtNum(c.max)}`;
    if (c.state === 'failed') return 'failed';
    if (c.state === 'checking') return 'checking';
    return 'waiting';
  }

  const studentCount = $derived(grid?.students.length ?? 0);
</script>

<svelte:head><title>{enrollment?.title ?? 'Course'} · DartBrains Grader</title></svelte:head>

<header class="course-head">
  <div>
    <h1>{enrollment?.title ?? offeringId}</h1>
    <p class="meta">
      {enrollment?.term ?? ''}, {studentCount} {studentCount === 1 ? 'student' : 'students'}{#if enrollment?.role === 'ta'}, teaching assistant view{/if}
    </p>
  </div>
  <div class="status">
    <span class="dot {stream}" aria-hidden="true"></span>
    <span class="muted small">{stream === 'open' ? 'Live' : stream === 'connecting' ? 'Connecting' : 'Not live'}, refreshed {fmtRelative(new Date(refreshedAt).toISOString())}</span>
    <button class="quiet small" onclick={() => refresh()}>Refresh</button>
  </div>
</header>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}

<section class="attention" aria-labelledby="attention-h">
  <h2 id="attention-h">Needs attention</h2>
  {#if triage === null}
    <Loading label="Checking" />
  {:else if attentionCount === 0}
    <p class="allclear">Nothing needs your attention right now.</p>
  {:else}
    <ul class="items">
      {#if waitingTotal > 0}
        {#each triage.awaiting_manual as a (a.question_id)}
          <li>
            <span class="mark grade" aria-hidden="true"></span>
            <div class="text">
              <strong>{a.count} {a.count === 1 ? 'submission' : 'submissions'} waiting for a grade</strong>
              on <span class="mono">{questionLabel(a.question_id, a.qid)}</span>{#if a.title}, {a.title}{/if}.
              <span class="muted">Oldest {fmtRelative(a.oldest_submitted_at)}.</span>
            </div>
            <a class="btn primary small" href="/o/{offeringId}/grade/{a.question_id}">Grade now</a>
          </li>
        {/each}
      {/if}
      {#if triage.inactive_students.length > 0}
        <li>
          <span class="mark warn" aria-hidden="true"></span>
          <div class="text">
            <strong>{triage.inactive_students.length} {triage.inactive_students.length === 1 ? 'student has' : 'students have'} been inactive for a week</strong>
            while an assignment is open:
            {#each triage.inactive_students as s, i (s.netid)}
              <a href="/o/{offeringId}/students/{s.netid}">{s.display_name ?? s.netid}</a>{i < triage.inactive_students.length - 1 ? ', ' : '.'}
            {/each}
          </div>
        </li>
      {/if}
      {#each triage.failing_checks as c (c.qid + c.check_key)}
        <li>
          <span class="mark warn" aria-hidden="true"></span>
          <div class="text">
            <strong>{fmtPercent(c.fail_rate)} of the class is failing the check</strong>
            <span class="mono">{c.check_key}</span> on <span class="mono">{c.qid}</span>
            <span class="muted">({c.n} students in the last two days).</span>
            {#if c.message}<span class="muted">{c.message}</span>{/if}
          </div>
        </li>
      {/each}
      {#if triage.grader_failures.length > 0}
        <li>
          <span class="mark bad" aria-hidden="true"></span>
          <div class="text">
            <strong>{triage.grader_failures.length} {triage.grader_failures.length === 1 ? 'submission' : 'submissions'} could not be graded.</strong>
            <ul class="failures">
              {#each triage.grader_failures as f (f.submission_id)}
                <li>
                  <a href="/o/{offeringId}/students/{f.netid}">{f.netid}</a>, <span class="mono">{questionLabel(f.question_id, f.qid)}</span>,
                  <span class="muted" title={fmtDateTime(f.submitted_at)}>{fmtRelative(f.submitted_at)}</span>
                  <code class="err" title={f.error ?? ''}>{(f.error ?? 'unknown error').slice(0, 90)}</code>
                  <button class="quiet small" disabled={retrying.has(f.submission_id)} onclick={() => retry(f.submission_id)}>
                    {retrying.has(f.submission_id) ? 'Retrying' : 'Retry'}
                  </button>
                </li>
              {/each}
            </ul>
          </div>
        </li>
      {/if}
    </ul>
  {/if}
</section>

<section class="roster" aria-labelledby="roster-h">
  <div class="roster-head">
    <h2 id="roster-h">Class progress</h2>
    {#if assignments.length > 1}
      <div class="tabs" role="tablist" aria-label="Assignment">
        {#each assignments as a (a.id)}
          <button role="tab" aria-selected={a.id === selectedAssignment} class:on={a.id === selectedAssignment} onclick={() => selectAssignment(a.id)}>{a.title}</button>
        {/each}
      </div>
    {:else if selected}
      <span class="muted">{selected.title}</span>
    {/if}
  </div>

  {#if grid === null}
    <Loading label="Loading class progress" />
  {:else if grid.students.length === 0}
    <p class="empty">No students on the roster yet. <a href="/o/{offeringId}/roster">Import the Canvas roster</a> to see progress here.</p>
  {:else if columns.length === 0}
    <p class="empty">No assignment published yet. <a href="/o/{offeringId}/assignments">Publish one</a> and its questions appear as columns here.</p>
  {:else}
    <div class="tablewrap">
      <table class="progress">
        <thead>
          <tr>
            <th class="student">Student</th>
            <th>Section</th>
            <th>Last activity</th>
            {#each columns as q (q.id)}
              <th class="q">
                {#if q.grading_mode !== 'auto'}
                  <a href="/o/{offeringId}/grade/{q.id}" title="Open the grading queue for {q.qid}"><span class="qid">{q.qid}</span><span class="qtitle">{q.title}</span></a>
                {:else}
                  <span class="qid">{q.qid}</span><span class="qtitle">{q.title}</span>
                {/if}
                <span class="qpts">{fmtNum(q.max_points)} pts{q.grading_mode === 'manual' ? ', graded by hand' : q.grading_mode === 'hybrid' ? ', partly by hand' : ''}</span>
              </th>
            {/each}
          </tr>
        </thead>
        <tbody>
          {#each grid.students as s (s.netid)}
            <tr>
              <td class="student"><a href="/o/{offeringId}/students/{s.netid}">{s.display_name || s.netid}</a><span class="netid">{s.netid}</span></td>
              <td class="muted">{s.section ?? '—'}</td>
              <td class="muted" title={fmtDateTime(s.last_activity)}>{s.last_activity ? fmtRelative(s.last_activity) : 'none yet'}</td>
              {#each columns as q (q.id)}
                {@const c = s.cells[q.id]}
                <td class="cell {c?.state ?? 'none'}" title={c?.attempts ? `${c.attempts} attempt${c.attempts === 1 ? '' : 's'}` : 'no submission'}>{cellText(c)}</td>
              {/each}
            </tr>
          {/each}
        </tbody>
        <tfoot>
          <tr>
            <td colspan="3" class="muted">Graded, waiting, not started</td>
            {#each columns as q (q.id)}
              {@const t = columnTotals.get(q.id)}
              <td class="cell foot">{t?.graded ?? 0}, {(t?.submitted ?? 0) + (t?.failed ?? 0) + (t?.checking ?? 0)}, {t?.none ?? 0}</td>
            {/each}
          </tr>
        </tfoot>
      </table>
    </div>
  {/if}
</section>

<style>
  .course-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    gap: 24px;
    flex-wrap: wrap;
    padding: 28px 0 8px;
  }
  .course-head h1 {
    font-size: 28px;
    font-weight: 600;
    letter-spacing: -0.01em;
    margin: 0;
    line-height: 1.15;
  }
  .course-head .meta {
    margin: 4px 0 0;
    color: var(--muted);
  }
  .status {
    display: flex;
    align-items: center;
    gap: 8px;
    padding-bottom: 6px;
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--rule);
  }
  .dot.open {
    background: var(--accent);
  }
  .dot.connecting {
    background: var(--warn);
  }

  section.attention {
    margin: 20px 0 36px;
    padding: 18px 20px;
    background: var(--surface);
    border-radius: 8px;
  }
  section.attention h2,
  section.roster h2 {
    font-size: 17px;
    font-weight: 600;
    margin: 0;
  }
  .allclear {
    margin: 8px 0 0;
    color: var(--muted);
  }
  .items {
    list-style: none;
    margin: 12px 0 0;
    padding: 0;
    display: grid;
    gap: 12px;
  }
  .items > li {
    display: grid;
    grid-template-columns: 10px 1fr auto;
    gap: 14px;
    align-items: start;
  }
  .mark {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    margin-top: 7px;
  }
  .mark.grade {
    background: var(--accent);
  }
  .mark.warn {
    background: var(--warn);
  }
  .mark.bad {
    background: var(--danger);
  }
  .text {
    line-height: 1.5;
    max-width: 72ch;
  }
  .failures {
    list-style: none;
    margin: 6px 0 0;
    padding: 0;
    display: grid;
    gap: 4px;
    font-size: 14px;
  }
  .failures li {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 8px;
    align-items: baseline;
  }
  code.err {
    font-size: 12px;
    background: var(--code-bg);
    padding: 1px 6px;
    border-radius: 3px;
    max-width: 48ch;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .roster-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }
  .tabs {
    display: inline-flex;
    border: 1px solid var(--rule);
    border-radius: 6px;
    overflow: hidden;
  }
  .tabs button {
    font: inherit;
    font-size: 14px;
    padding: 5px 12px;
    border: 0;
    background: transparent;
    color: var(--muted);
    cursor: pointer;
  }
  .tabs button + button {
    border-left: 1px solid var(--rule);
  }
  .tabs button.on {
    background: var(--accent);
    color: var(--accent-ink);
  }
  .tabs button:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }

  .tablewrap {
    overflow-x: auto;
  }
  table.progress {
    width: 100%;
    border-collapse: collapse;
    font-variant-numeric: tabular-nums;
    font-size: 15px;
  }
  table.progress th,
  table.progress td {
    text-align: left;
    padding: 10px 12px;
    border-bottom: 1px solid var(--rule);
    vertical-align: top;
  }
  table.progress thead th {
    font-weight: 600;
    font-size: 13px;
    color: var(--muted);
    border-bottom: 2px solid var(--rule);
    vertical-align: bottom;
  }
  th.q {
    min-width: 120px;
  }
  th.q a {
    color: inherit;
    text-decoration: none;
  }
  th.q a:hover .qid {
    text-decoration: underline;
  }
  .qid {
    display: block;
    font-family: var(--mono);
    font-size: 13px;
    color: var(--ink);
  }
  .qtitle {
    display: block;
    font-weight: 400;
    color: var(--ink);
    max-width: 18ch;
    line-height: 1.3;
  }
  .qpts {
    display: block;
    font-weight: 400;
    font-size: 12px;
    margin-top: 2px;
  }
  td.student {
    position: sticky;
    left: 0;
    background: var(--paper);
    min-width: 180px;
  }
  td.student a {
    font-weight: 600;
  }
  .netid {
    display: block;
    font-family: var(--mono);
    font-size: 12px;
    color: var(--muted);
  }
  td.cell {
    font-family: var(--mono);
    font-size: 14px;
    white-space: nowrap;
  }
  td.cell.none {
    color: var(--rule);
  }
  td.cell.graded {
    color: var(--accent);
    font-weight: 600;
  }
  td.cell.submitted,
  td.cell.checking {
    color: var(--warn);
  }
  td.cell.failed {
    color: var(--danger);
  }
  tfoot td {
    font-size: 13px;
    color: var(--muted);
    border-bottom: 0;
  }
  td.cell.foot {
    color: var(--muted);
    font-weight: 400;
  }
  tbody tr:hover td {
    background: var(--surface);
  }
  .empty {
    color: var(--muted);
  }
  @media (max-width: 640px) {
    .items > li {
      grid-template-columns: 10px 1fr;
    }
    .items > li .btn {
      grid-column: 2;
    }
  }
</style>
