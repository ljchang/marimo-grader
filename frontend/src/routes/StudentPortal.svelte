<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, type Assignment, type Submission } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import { countingAttempt, fmtDateTime, fmtPoints, fmtPolicy, statusLabel, submissionPoints, trim } from '$lib/format';
  import type { Params } from '$lib/router.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import StateChip from '$lib/components/StateChip.svelte';
  import RenderFrame from '$lib/components/RenderFrame.svelte';

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
      status: allGraded ? 'graded' : anyGraded ? 'graded' : 'submitted',
      points: anyGraded ? points : null,
      max,
      attempts: subs.length,
      lastAt,
    };
  }

  function attemptsFor(a: Assignment, questionId: string): Submission[] {
    return (submissions[a.id] ?? [])
      .filter((s) => s.question_id === questionId)
      .sort((x, y) => y.attempt_no - x.attempt_no);
  }

  onMount(async () => {
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
  });
</script>

<div class="page-head">
  <div>
    <p class="eyebrow">{enrollment?.course_slug ?? ''} · {enrollment?.term ?? ''}</p>
    <h1>{enrollment?.title ?? 'Assignments'}</h1>
  </div>
  <div class="meta"><span>{auth.me?.display_name ?? auth.me?.netid}</span></div>
</div>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}

{#if assignments === null}
  <Loading />
{:else if assignments.length === 0}
  <p class="empty">No assignments have been released yet.</p>
{:else}
  <div class="tablewrap">
    <table class="data">
      <thead>
        <tr>
          <th>Assignment</th>
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
          <tr>
            <td class="wrap"><strong>{a.title}</strong><span class="sub">{a.questions.length} question{a.questions.length === 1 ? '' : 's'} · {fmtPolicy(a.settings.grade_policy)}</span></td>
            <td>{a.settings.due_at ? fmtDateTime(a.settings.due_at) : '—'}</td>
            <td><span class="chip {s.status === 'graded' ? 'graded' : s.status === 'submitted' ? 'submitted' : 'none'}">{s.status}</span></td>
            <td class="num">{fmtPoints(s.points, s.max)}</td>
            <td class="num">{a.settings.attempts_allowed ? `${s.attempts} / ${a.settings.attempts_allowed}` : s.attempts}</td>
            <td>
              {#if s.attempts > 0}
                <button class="quiet" onclick={() => (expanded = expanded === a.id ? null : a.id)}>{expanded === a.id ? 'Hide attempts' : 'Attempts and feedback'}</button>
              {/if}
            </td>
          </tr>
          {#if expanded === a.id}
            <tr class="detail">
              <td colspan="6" class="wrap">
                {#each [...a.questions].sort((x, y) => x.order - y.order) as q (q.id)}
                  {@const attempts = attemptsFor(a, q.id)}
                  <div class="question">
                    <h3><span class="mono">{q.qid}</span> {q.title} <span class="muted small num">{trim(q.max_points)} pts</span></h3>
                    {#if attempts.length === 0}
                      <p class="empty">No attempts.</p>
                    {:else}
                      <table class="data attempts">
                        <thead><tr><th class="num">Attempt</th><th>Submitted</th><th>Status</th><th class="num">Points</th><th>Feedback</th><th></th></tr></thead>
                        <tbody>
                          {#each attempts as sub (sub.id)}
                            <tr class:counts={countingAttempt(attempts, a.settings.grade_policy)?.id === sub.id}>
                              <td class="num">{sub.attempt_no}</td>
                              <td>{fmtDateTime(sub.submitted_at)}</td>
                              <td><StateChip state={sub.status} /> {#if sub.status !== 'graded'}<span class="muted small">{statusLabel(sub.status)}</span>{/if}</td>
                              <td class="num">{fmtPoints(submissionPoints(sub), q.max_points)}</td>
                              <td class="wrap feedback">{sub.score?.feedback ?? sub.feedback ?? ''}</td>
                              <td>{#if sub.render_url}<button class="quiet" onclick={() => (open = open === sub.id ? null : sub.id)}>{open === sub.id ? 'Hide' : 'View'}</button>{/if}</td>
                            </tr>
                            {#if open === sub.id}
                              <tr><td colspan="6" class="wrap"><RenderFrame src={sub.render_url} title="Attempt {sub.attempt_no}" height="520px" /></td></tr>
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
  tr.counts td:first-child {
    font-weight: 600;
  }
  td.feedback {
    max-width: 44ch;
    color: var(--ink);
  }
</style>
