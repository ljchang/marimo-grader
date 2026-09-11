<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, type Assignment, type StudentHistory, type Submission } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import { fmtDateTime, fmtPoints, submissionPoints } from '$lib/format';
  import type { Params } from '$lib/router.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import StateChip from '$lib/components/StateChip.svelte';
  import RenderFrame from '$lib/components/RenderFrame.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const netid = $derived(params.netid ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  let history = $state<StudentHistory | null>(null);
  let assignments = $state<Assignment[]>([]);
  let error = $state<string | null>(null);
  let open = $state<string | null>(null);

  interface QuestionGroup {
    question_id: string;
    qid: string;
    title: string;
    max_points: number | null;
    attempts: Submission[];
  }
  interface AssignmentGroup {
    key: string;
    title: string;
    questions: QuestionGroup[];
  }

  const groups = $derived.by((): AssignmentGroup[] => {
    if (!history) return [];
    const byAssignment = new Map<string, AssignmentGroup>();
    const questionMeta = new Map<string, { qid: string; title: string; max: number; assignment: Assignment; order: number }>();
    for (const a of assignments) {
      for (const q of a.questions) {
        questionMeta.set(q.id, { qid: q.qid, title: q.title, max: q.max_points, assignment: a, order: q.order });
      }
    }
    for (const s of history.submissions) {
      const meta = questionMeta.get(s.question_id);
      const key = meta?.assignment.id ?? s.assignment_id ?? s.assignment_version_id;
      const title = meta?.assignment.title ?? s.assignment_title ?? s.assignment_slug ?? 'Assignment';
      let ag = byAssignment.get(key);
      if (!ag) {
        ag = { key, title, questions: [] };
        byAssignment.set(key, ag);
      }
      let qg = ag.questions.find((q) => q.question_id === s.question_id);
      if (!qg) {
        qg = {
          question_id: s.question_id,
          qid: meta?.qid ?? s.qid ?? s.question_id,
          title: meta?.title ?? s.question_title ?? '',
          max_points: meta?.max ?? s.max_points ?? null,
          attempts: [],
        };
        ag.questions.push(qg);
      }
      qg.attempts.push(s);
    }
    for (const ag of byAssignment.values()) {
      ag.questions.sort((a, b) => (questionMeta.get(a.question_id)?.order ?? 0) - (questionMeta.get(b.question_id)?.order ?? 0));
      for (const q of ag.questions) q.attempts.sort((a, b) => b.attempt_no - a.attempt_no);
    }
    return [...byAssignment.values()];
  });

  onMount(async () => {
    try {
      const [h, a] = await Promise.all([
        api.grading.student(offeringId, netid),
        api.offerings.assignments(offeringId),
      ]);
      history = h;
      assignments = a;
    } catch (err) {
      error = errorMessage(err);
    }
  });
</script>

<div class="page-head">
  <div>
    <p class="eyebrow"><a href="/o/{offeringId}">{enrollment?.title ?? 'Triage'}</a> · student</p>
    <h1>{history?.display_name ?? netid} <span class="muted mono" style="font-weight:400;font-size:15px">{netid}</span></h1>
  </div>
  <div class="meta">
    {#if history?.section}<span>Section {history.section}</span>{/if}
    <span>{history?.submissions.length ?? 0} submissions</span>
  </div>
</div>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}

{#if history === null && !error}
  <Loading />
{:else if groups.length === 0}
  <p class="empty">No submissions yet.</p>
{:else}
  {#each groups as ag (ag.key)}
    <section class="block">
      <div class="block-head"><h2>{ag.title}</h2></div>
      <div class="tablewrap">
        <table class="data">
          <thead>
            <tr>
              <th>Question</th>
              <th class="num">Attempt</th>
              <th>Submitted</th>
              <th>Status</th>
              <th class="num">Points</th>
              <th>Feedback</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {#each ag.questions as q (q.question_id)}
              {#each q.attempts as s, i (s.id)}
                <tr>
                  <td>
                    {#if i === 0}<span class="mono">{q.qid}</span><span class="sub">{q.title}</span>{/if}
                  </td>
                  <td class="num">{s.attempt_no}</td>
                  <td>{fmtDateTime(s.submitted_at)}</td>
                  <td><StateChip state={s.status} /></td>
                  <td class="num">{fmtPoints(submissionPoints(s), q.max_points)}</td>
                  <td class="wrap feedback">{s.score?.feedback ?? s.feedback ?? ''}</td>
                  <td>
                    {#if s.render_url}
                      <button class="quiet" onclick={() => (open = open === s.id ? null : s.id)}>{open === s.id ? 'Hide' : 'View'}</button>
                    {/if}
                  </td>
                </tr>
                {#if open === s.id}
                  <tr><td colspan="7" class="wrap"><RenderFrame src={s.render_url} title="Attempt {s.attempt_no} by {netid}" height="560px" /></td></tr>
                {/if}
              {/each}
            {/each}
          </tbody>
        </table>
      </div>
    </section>
  {/each}
{/if}

<style>
  td.feedback {
    max-width: 36ch;
    color: var(--muted);
  }
</style>
