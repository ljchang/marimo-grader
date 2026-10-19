<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, type Assignment, type Submission } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import { countingAttempt, fmtDateTime, fmtPoints, fmtPolicy, statusLabel, submissionPoints, trim } from '$lib/format';
  import type { Params } from '$lib/router.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import StateChip from '$lib/components/StateChip.svelte';
  import SubmissionView from '$lib/components/SubmissionView.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  let assignments = $state<Assignment[] | null>(null);
  let submissions = $state<Record<string, Submission[]>>({});
  let error = $state<string | null>(null);
  let expanded = $state<string | null>(null);
  let open = $state<string | null>(null);

  interface Summary {
    status: 'not started' | 'in progress' | 'submitted' | 'graded';
    points: number | null;
    max: number;
    attempts: number;
    lastAt: string | null;
  }

  function summarize(a: Assignment): Summary {
    const subs = submissions[a.id] ?? [];
    const max = a.questions.reduce((n, q) => n + q.max_points, 0);
    if (subs.length === 0) return { status: 'not started', points: null, max, attempts: 0, lastAt: null };
    let points = 0;
    let anyGraded = false;
    let allGraded = a.questions.length > 0;
    for (const q of a.questions) {
      const attempts = subs.filter((s) => s.question_id === q.id);
      const counting = countingAttempt(attempts, a.settings.grade_policy);
      const p = counting ? submissionPoints(counting) : null;
      if (counting?.status === 'graded' && p !== null) {
        points += p;
        anyGraded = true;
      } else {
        allGraded = false;
      }
    }
    const lastAt = subs.reduce<string | null>((m, s) => (!m || s.submitted_at > m ? s.submitted_at : m), null);
    return {
      status: allGraded ? 'graded' : anyGraded ? 'in progress' : 'submitted',
      points: anyGraded ? points : null,
      max,
      attempts: subs.length,
      lastAt,
    };
  }

  /** Stable /a/ links; the server checks the session and the window again on click. */
  function notebookUrl(a: Assignment, what: 'molab' | 'student.py'): string | null {
    if (!enrollment || a.latest_version === null) return null;
    return `/a/${enrollment.course_slug}/${enrollment.term}/${a.slug}/${what}`;
  }

  // The launch link from a course page lands here as /me/<offering>#<slug>.
  const launched = typeof location !== 'undefined' ? decodeURIComponent(location.hash.slice(1)) : '';

  function attemptsFor(a: Assignment, questionId: string): Submission[] {
    return (submissions[a.id] ?? [])
      .filter((s) => s.question_id === questionId)
      .sort((x, y) => y.attempt_no - x.attempt_no);
  }

  let switching = $state(false);
  async function startPreview() {
    switching = true;
    try {
      await auth.setPreview(offeringId, true);
      await load();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      switching = false;
    }
  }

  onMount(load);

  async function load() {
    assignments = null;
    error = null;
    try {
      const list = await api.offerings.assignments(offeringId);
      assignments = list;
      const results = await Promise.all(
        list.map(async (a) => [a.id, await api.submissions.mine(offeringId, a.id)] as const),
      );
      const map: Record<string, Submission[]> = {};
      for (const [id, subs] of results) map[id] = subs;
      submissions = map;
    } catch (err) {
      error = errorMessage(err);
      assignments ??= [];
    }
  }
</script>

<div class="page-head">
  <div>
    <h1>{enrollment?.title ?? 'Assignments'}</h1>
    <p class="eyebrow">{enrollment?.term ?? ''}, signed in as {auth.me?.display_name ?? auth.me?.netid}</p>
  </div>
  {#if auth.canPreview(offeringId) && !enrollment?.preview}
    <div class="preview-offer">
      <button onclick={startPreview} disabled={switching}>{switching ? 'Switching…' : 'Preview as a student'}</button>
      <span class="sub">Held to deadlines and closing dates like a student, with student access to data, but assignments open before their release date. Submissions are tests.</span>
    </div>
  {/if}
</div>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}

{#if assignments === null}
  <Loading />
{:else if assignments.length === 0}
  <p class="empty">No assignments have been released yet. They appear here as your instructor publishes them.</p>
{:else}
  <div class="tablewrap">
    <table class="data">
      <thead>
        <tr>
          <th>Assignment</th>
          <th>Open</th>
          <th>Due</th>
          <th>Status</th>
          <th class="num">Grade</th>
          <th class="num">Attempts</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        {#each assignments as a (a.id)}
          {@const s = summarize(a)}
          {@const av = a.availability}
          {@const molab = notebookUrl(a, 'molab')}
          {@const download = notebookUrl(a, 'student.py')}
          <tr id={a.slug} class:launched={launched === a.slug}>
            <td class="wrap"><strong>{a.title}</strong><span class="sub">{a.questions.length} question{a.questions.length === 1 ? '' : 's'}, {fmtPolicy(a.settings.grade_policy)}</span></td>
            <td class="wrap">
              {#if av?.state === 'upcoming'}
                <span class="muted small">Opens {fmtDateTime(av.release_at)}</span>
              {:else if av?.state === 'closed'}
                <span class="muted small">Closed {fmtDateTime(av.close_at)}</span>
              {:else if molab && download}
                <a class="btn small" href={molab} target="_blank" rel="noopener" data-native>Open in molab</a>
                <a class="quiet small" href={download} download="{a.slug}.py" data-native>Download .py</a>
                {#if av?.close_at}<span class="sub">Closes {fmtDateTime(av.close_at)}</span>{/if}
              {:else}
                <span class="muted small">Not published yet</span>
              {/if}
            </td>
            <td>{a.settings.due_at ? fmtDateTime(a.settings.due_at) : '—'}{#if av?.past_due}<span class="sub">past due{a.settings.late_policy === 'reject' ? ', closed to submissions' : ''}</span>{/if}</td>
            <td><span class="chip {s.status === 'graded' ? 'graded' : s.status === 'submitted' ? 'submitted' : s.status === 'in progress' ? 'progress' : 'none'}">{s.status === 'submitted' ? 'waiting for grade' : s.status}</span></td>
            <td class="num">{fmtPoints(s.points, s.max)}</td>
            <td class="num">{a.settings.attempts_allowed ? `${s.attempts} / ${a.settings.attempts_allowed}` : s.attempts}</td>
            <td>
              {#if s.attempts > 0}
                <button class="quiet" onclick={() => (expanded = expanded === a.id ? null : a.id)}>{expanded === a.id ? 'Hide attempts' : 'See attempts and feedback'}</button>
              {/if}
            </td>
          </tr>
          {#if expanded === a.id}
            <tr class="detail">
              <td colspan="7" class="wrap">
                {#each [...a.questions].sort((x, y) => x.order - y.order) as q (q.id)}
                  {@const attempts = attemptsFor(a, q.id)}
                  <div class="question">
                    <h3><span class="mono">{q.qid}</span> {q.title && q.title !== q.qid ? q.title : ''} <span class="muted small num">{trim(q.max_points)} pts</span></h3>
                    {#if attempts.length === 0}
                      <p class="empty">Not submitted yet.</p>
                    {:else}
                      <table class="data attempts">
                        <thead><tr><th class="num">Attempt</th><th>Submitted</th><th>Status</th><th class="num">Points</th><th>Feedback</th><th></th></tr></thead>
                        <tbody>
                          {#each attempts as sub (sub.id)}
                            <tr class:counts={countingAttempt(attempts, a.settings.grade_policy)?.id === sub.id}>
                              <td class="num">{sub.attempt_no}</td>
                              <td>{fmtDateTime(sub.submitted_at)}{#if sub.late} <span class="chip late">late</span>{/if}</td>
                              <td><StateChip state={sub.status} /> {#if sub.status !== 'graded'}<span class="muted small">{statusLabel(sub.status)}</span>{/if}</td>
                              <td class="num">{fmtPoints(submissionPoints(sub), q.max_points)}</td>
                              <td class="wrap feedback">{sub.score?.feedback ?? sub.feedback ?? ''}</td>
                              <td>{#if sub.render_url || sub.renders === false}<button class="quiet" onclick={() => (open = open === sub.id ? null : sub.id)}>{open === sub.id ? 'Hide' : 'View'}</button>{/if}</td>
                            </tr>
                            {#if open === sub.id}
                              <tr><td colspan="6" class="wrap"><SubmissionView submission={sub} height="520px" /></td></tr>
                            {/if}
                          {/each}
                        </tbody>
                      </table>
                    {/if}
                  </div>
                {/each}
              </td>
            </tr>
          {/if}
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .preview-offer {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 4px;
    max-width: 340px;
    text-align: right;
  }
  tr.detail > td {
    background: var(--surface);
    padding: 12px 14px 4px;
  }
  tr.detail:hover > td {
    background: var(--surface);
  }
  .question {
    margin-bottom: 14px;
  }
  .question h3 {
    margin-bottom: 4px;
  }
  table.attempts th {
    background: var(--surface);
  }
  tr.launched > td {
    background: var(--surface);
  }
  .chip.late {
    margin-left: 4px;
    color: var(--warn);
  }
  tr.counts td:first-child {
    font-weight: 600;
  }
  td.feedback {
    max-width: 44ch;
    white-space: normal;
    color: var(--ink);
  }
</style>
