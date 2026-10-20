<script lang="ts">
  // One assignment, for its instructor: where it stands, and where the class
  // stands on each question. Everything else is in Settings or More.
  import { onMount } from 'svelte';
  import { api, errorMessage, type Assignment, type Progress, type ProgressState } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import {
    copyStudentLink,
    exportCanvas,
    gradeHref,
    hidden,
    phase,
    previewAsStudent,
    relative,
    tags,
    uploadLabel,
  } from '$lib/assignmentView';
  import { fmtDateTime, trim } from '$lib/format';
  import type { Params } from '$lib/router.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import MoreMenu from '$lib/components/MoreMenu.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import SettingsPanel from '$lib/components/SettingsPanel.svelte';
  import UploadNotebookPanel from '$lib/components/UploadNotebookPanel.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const assignmentId = $derived(params.assignment ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  let a = $state<Assignment | null>(null);
  let progress = $state<Progress | null>(null);
  let loaded = $state(false);
  let error = $state<string | null>(null);
  let message = $state<string | null>(null);
  let showSettings = $state(false);
  let showUpload = $state(false);

  async function load() {
    try {
      const [list, p] = await Promise.all([
        api.offerings.assignments(offeringId),
        api.grading.progress(offeringId, assignmentId).catch(() => null),
      ]);
      a = list.find((x) => x.id === assignmentId) ?? null;
      progress = p;
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loaded = true;
    }
  }
  onMount(load);

  const p = $derived(a ? progress?.assignments[a.id] : undefined);
  const roster = $derived(progress?.roster ?? 0);
  const students = $derived(progress?.students ?? []);
  const questions = $derived(a ? [...a.questions].sort((x, y) => x.order - y.order) : []);

  /** The one sentence under the title: whether students can work on it, and until when. */
  const status = $derived.by(() => {
    if (!a) return { word: '', rest: '' };
    const s = a.settings;
    switch (phase(a)) {
      case 'upcoming':
        if (hidden(a)) return { word: 'Hidden', rest: ' from students: it has no open date yet.' };
        return { word: 'Opens', rest: ` ${fmtDateTime(s.release_at)} (${relative(s.release_at!)}).` };
      case 'closed':
        return { word: 'Closed', rest: ` ${fmtDateTime(s.close_at)}.` };
      default: {
        if (!s.due_at) return { word: 'Open', rest: ', no due date.' };
        const past = new Date(s.due_at).getTime() < Date.now();
        const late = s.late_policy === 'reject' ? 'late work refused' : 'late work accepted';
        return past
          ? { word: 'Open', rest: `, was due ${fmtDateTime(s.due_at)}; ${late}.` }
          : { word: 'Open', rest: `, due ${fmtDateTime(s.due_at)} (${relative(s.due_at)}).` };
      }
    }
  });

  const MARK_WORDS: Record<ProgressState, string> = {
    graded: 'graded',
    waiting: 'waiting for you',
    failed: 'failed to run',
    running: 'being graded',
    none: 'not submitted',
  };
  const TALLY: ProgressState[] = ['graded', 'waiting', 'failed', 'running', 'none'];

  const graded = (mode: string) =>
    a?.settings.autograde === false || mode === 'manual'
      ? 'graded by hand'
      : mode === 'hybrid'
        ? 'partly graded by hand'
        : 'graded automatically';

  const menu = $derived(
    a
      ? [
          {
            label: 'Copy student link',
            onselect: () =>
              copyStudentLink(enrollment, a!)
                .then(() => (message = 'Copied the student link. It signs a student in and opens this assignment.'))
                .catch((err) => (error = errorMessage(err))),
          },
          { label: 'Preview as a student', onselect: () => previewAsStudent(offeringId).catch((err) => (error = errorMessage(err))) },
          { label: uploadLabel(a), onselect: () => (showUpload = true) },
          { label: 'Export to Canvas', onselect: () => exportCanvas(offeringId, [a!.id]) },
        ]
      : [],
  );
</script>

{#if !loaded}
  <Loading />
{:else if !a}
  <Notice kind="warn" label="Not found">No such assignment. <a href="/o/{offeringId}/assignments">Back to assignments</a>.</Notice>
{:else}
  <div class="page-head head">
    <div>
      <p class="eyebrow"><a href="/o/{offeringId}/assignments">Assignments</a></p>
      <h1>{a.title}</h1>
      <p class="status">
        <span class="word {phase(a)}" class:hidden={hidden(a)}>{status.word}</span>{status.rest}
        {#if p && !(phase(a) === 'upcoming' && p.submitted === 0)}
          {p.submitted} of {roster} {roster === 1 ? 'student has' : 'students have'} submitted.
        {/if}
      </p>
      {#if tags(a).filter((t) => !t.warn).length}
        <p class="tags">{#each tags(a).filter((t) => !t.warn) as t (t.label)}<span class="tag" title={t.title}>{t.label}</span>{/each}</p>
      {/if}
    </div>
    <div class="row">
      {#if p && p.to_grade > 0}
        <a class="btn primary" href={gradeHref(offeringId, a, p)}>Grade {p.to_grade} {p.to_grade === 1 ? 'answer' : 'answers'}</a>
      {/if}
      <button onclick={() => (showSettings = true)}>Settings</button>
      <MoreMenu items={menu} />
    </div>
  </div>

  {#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}
  {#if message}<Notice label="Done">{message}</Notice>{/if}

  <section class="grading">
    <div class="section-head">
      <h2>Grading</h2>
      {#if questions.length && roster}<p class="muted small">One mark per student. Click a mark to open that student's answer.</p>{/if}
    </div>

    {#if questions.length === 0}
      <p class="empty">No questions yet. <button class="quiet" onclick={() => (showUpload = true)}>{uploadLabel(a)}</button></p>
    {:else}
      {#each questions as q (q.id)}
        {@const qp = p?.questions[q.id]}
        {@const marks = qp?.marks ?? []}
        <div class="q">
          <div class="q-head">
            <div>
              <div class="q-title">
                {#if q.qid === 'notebook'}Whole notebook{:else}<span class="mono qid">{q.qid}</span>{q.title === q.qid ? '' : q.title}{/if}
              </div>
              <div class="muted small">{trim(q.max_points)} {q.max_points === 1 ? 'point' : 'points'}, {graded(q.grading_mode)}</div>
            </div>
            {#if qp && qp.counts.waiting > 0}
              <a class="btn primary" href="/o/{offeringId}/grade/{q.id}">Grade {qp.counts.waiting}</a>
            {:else if qp && qp.counts.none < roster}
              <a class="btn" href="/o/{offeringId}/grade/{q.id}">Review answers</a>
            {/if}
          </div>
          {#if marks.length}
            <div class="strip" style:--n={marks.length}>
              {#each marks as st, i (students[i]?.netid ?? i)}
                {@const who = students[i]?.display_name || students[i]?.netid || 'Student'}
                {#if st === 'none'}
                  <span class="mark none" title="{who}: {MARK_WORDS[st]}"></span>
                {:else}
                  <a
                    class="mark {st}"
                    href="/o/{offeringId}/grade/{q.id}?netid={encodeURIComponent(students[i]?.netid ?? '')}"
                    title="{who}: {MARK_WORDS[st]}"
                    aria-label="{who}: {MARK_WORDS[st]}"
                    tabindex="-1"
                  ></a>
                {/if}
              {/each}
            </div>
          {/if}
          {#if qp}
            <p class="tally">
              {#each TALLY.filter((s) => qp.counts[s] > 0) as s (s)}
                <span class={s}><b>{qp.counts[s]}</b> {MARK_WORDS[s]}</span>
              {/each}
            </p>
          {/if}
        </div>
      {/each}
    {/if}
  </section>

  {#if showSettings}
    <SettingsPanel
      {offeringId}
      assignment={a}
      onclose={() => (showSettings = false)}
      onsaved={() => {
        showSettings = false;
        message = 'Settings saved.';
        void load();
      }}
    />
  {/if}

  {#if showUpload}
    <UploadNotebookPanel
      {offeringId}
      assignment={a}
      onclose={() => (showUpload = false)}
      onpublished={(m) => {
        showUpload = false;
        message = m;
        void load();
      }}
    />
  {/if}
{/if}

<style>
  .head {
    align-items: flex-start;
  }
  .head > div:first-child {
    flex: 1;
    min-width: 0;
  }
  .status {
    margin: 6px 0 0;
    font-size: 16px;
    max-width: 80ch;
  }
  .word {
    font-weight: 600;
  }
  .word.open {
    color: var(--accent);
  }
  .word.hidden {
    color: var(--warn);
  }
  .tags {
    display: flex;
    gap: 6px;
    margin: 8px 0 0;
  }
  .tag {
    font-size: 12px;
    padding: 0 7px;
    border-radius: 9px;
    border: 1px solid var(--rule);
    color: var(--muted);
  }
  .grading {
    margin-top: 32px;
  }
  .section-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 16px;
    flex-wrap: wrap;
    padding-bottom: 8px;
    border-bottom: 1px solid var(--rule);
  }
  .section-head h2 {
    margin: 0;
    font-size: 19px;
  }
  .section-head p {
    margin: 0;
  }
  .q {
    padding: 16px 0;
    border-bottom: 1px solid var(--rule);
  }
  .q-head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 16px;
  }
  .q-title {
    font-size: 16px;
  }
  .qid {
    color: var(--muted);
    margin-right: 10px;
  }
  /* The roster strip: one mark per enrolled student, stretched across the row. */
  .strip {
    display: grid;
    grid-template-columns: repeat(var(--n), minmax(3px, 1fr));
    gap: 3px;
    margin-top: 12px;
  }
  .mark {
    display: block;
    height: 18px;
    border-radius: 2px;
    background: var(--rule);
  }
  a.mark:hover {
    outline: 2px solid var(--ink);
    outline-offset: 1px;
  }
  .mark.graded {
    background: var(--accent);
  }
  .mark.waiting {
    background: var(--warn);
  }
  .mark.failed {
    background: var(--danger);
  }
  .mark.running {
    background: var(--muted);
  }
  .tally {
    display: flex;
    flex-wrap: wrap;
    gap: 4px 18px;
    margin: 6px 0 0;
    font-size: 13px;
    color: var(--muted);
  }
  .tally b {
    color: var(--ink);
    font-weight: 600;
  }
  .tally .waiting b {
    color: var(--warn);
  }
  .tally .failed b {
    color: var(--danger);
  }
</style>
