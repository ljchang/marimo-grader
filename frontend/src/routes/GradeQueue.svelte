<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import {
    api,
    errorMessage,
    type Assignment,
    type Question,
    type RubricItem,
    type Submission,
  } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import { subscribeEvents, type StreamState } from '$lib/events';
  import { fmtDateTime, fmtRelative, trim } from '$lib/format';
  import type { Params } from '$lib/router.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import RenderFrame from '$lib/components/RenderFrame.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const questionId = $derived(params.questionId ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  interface Item extends Submission {
    done: boolean;
  }

  let question = $state<(Question & { assignment: Assignment }) | null>(null);
  let items = $state<Item[]>([]);
  let index = $state(0);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let stream = $state<StreamState>('closed');
  let pendingNew = $state(0);

  // Form state for the current item
  let rubricScores = $state<Record<string, number | null>>({});
  let manualPoints = $state<number | null>(null);
  let manualTouched = $state(false);
  let feedback = $state('');
  let final = $state(true);
  let submitting = $state(false);
  let flash = $state<string | null>(null);

  let feedbackEl = $state<HTMLTextAreaElement | null>(null);

  const current = $derived(items[index] ?? null);
  const rubric = $derived<RubricItem[]>(current?.rubric ?? question?.rubric ?? []);
  const maxPoints = $derived(current?.max_points ?? question?.max_points ?? null);
  const doneCount = $derived(items.filter((i) => i.done).length);
  const rubricSum = $derived(
    rubric.reduce((sum, r) => sum + (rubricScores[r.key] ?? 0), 0),
  );
  const effectiveManual = $derived(
    manualTouched || rubric.length === 0 ? manualPoints : rubricSum,
  );

  function resetForm(item: Item | null) {
    const sc = item?.score ?? null;
    const scores: Record<string, number | null> = {};
    for (const r of rubric) scores[r.key] = sc?.rubric_scores?.[r.key] ?? null;
    rubricScores = scores;
    manualPoints = sc?.manual_points ?? null;
    manualTouched = sc?.manual_points != null && rubric.length === 0;
    feedback = sc?.feedback ?? item?.feedback ?? '';
    final = sc?.final ?? true;
    flash = null;
  }

  function go(to: number) {
    if (items.length === 0) return;
    index = Math.max(0, Math.min(items.length - 1, to));
    pendingNew = 0;
    resetForm(items[index] ?? null);
  }

  function next() {
    // Prefer the next ungraded item; otherwise just step forward.
    const after = items.findIndex((it, i) => i > index && !it.done);
    if (after >= 0) go(after);
    else if (index < items.length - 1) go(index + 1);
  }

  function prev() {
    if (index > 0) go(index - 1);
  }

  async function load() {
    loading = true;
    error = null;
    try {
      const [assignments, queue] = await Promise.all([
        api.offerings.assignments(offeringId),
        api.grading.queue(offeringId, questionId),
      ]);
      for (const a of assignments) {
        const q = a.questions.find((x) => x.id === questionId);
        if (q) question = { ...q, assignment: a, rubric: queue.question.rubric ?? q.rubric };
      }
      items = queue.items.map((s) => ({ ...s, done: false }));
      index = 0;
      resetForm(items[0] ?? null);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loading = false;
    }
  }

  /** Pull in newly arrived submissions without losing the grader's place. */
  async function mergeQueue() {
    try {
      const queue = await api.grading.queue(offeringId, questionId);
      const known = new Set(items.map((i) => i.id));
      const fresh = queue.items.filter((s) => !known.has(s.id));
      if (fresh.length > 0) {
        items = [...items, ...fresh.map((s) => ({ ...s, done: false }))];
        pendingNew += fresh.length;
      }
    } catch {
      // keep working with what we have
    }
  }

  let unsubscribe: (() => void) | null = null;

  onMount(async () => {
    await load();
    unsubscribe = subscribeEvents(
      offeringId,
      (ev) => {
        if (ev.question_id === questionId && ev.type === 'submission.received') {
          void mergeQueue();
        }
      },
      (s) => (stream = s),
    );
  });

  onDestroy(() => unsubscribe?.());

  async function submit() {
    const item = current;
    if (!item || submitting) return;
    submitting = true;
    error = null;
    const rubric_scores: Record<string, number> = {};
    for (const [k, v] of Object.entries(rubricScores)) if (v !== null) rubric_scores[k] = v;
    try {
      const score = await api.grading.score(item.id, {
        manual_points: effectiveManual,
        rubric_scores,
        feedback,
        final,
      });
      items = items.map((it) =>
        it.id === item.id ? { ...it, done: true, score, status: 'graded' } : it,
      );
      flash = `Saved ${item.netid}`;
      await tick();
      next();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      submitting = false;
    }
  }

  function isEditable(target: EventTarget | null): boolean {
    if (!(target instanceof HTMLElement)) return false;
    const tag = target.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
  }

  function onKey(e: KeyboardEvent) {
    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
      e.preventDefault();
      void submit();
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (isEditable(e.target)) return;
    if (e.key === 'j') {
      e.preventDefault();
      next();
    } else if (e.key === 'k') {
      e.preventDefault();
      prev();
    } else if (e.key === 'f') {
      e.preventDefault();
      feedbackEl?.focus();
    }
  }

  function clampRubric(r: RubricItem) {
    const v = rubricScores[r.key];
    if (v === null || v === undefined) return;
    rubricScores[r.key] = Math.max(0, Math.min(r.max_points, v));
  }
</script>

<svelte:window onkeydown={onKey} />

<div class="queue">
  <header class="bar">
    <div class="left">
      <a href="/o/{offeringId}" class="back">{enrollment?.title ?? 'Course'}</a>
      <span class="muted">/</span>
      <span class="mono">{question?.qid ?? questionId}</span>
      {#if question}
        <span class="muted">{question.assignment.title}{question.title && question.title !== question.qid ? `, ${question.title}` : ''}{#if maxPoints !== null}, {trim(maxPoints)} pts{/if}</span>
      {/if}
    </div>
    <div class="right">
      <span class="live {stream}"></span>
      {#if pendingNew > 0}<span class="muted small">{pendingNew} new in queue</span>{/if}
      <span class="progress num">{doneCount} of {items.length} graded</span>
    </div>
  </header>

  {#if error}<div class="pad"><Notice kind="error" label="Error">{error}</Notice></div>{/if}

  {#if loading}
    <div class="pad"><Loading label="Loading queue" /></div>
  {:else if items.length === 0}
    <div class="pad">
      <p class="empty">Nothing is waiting for a grade on this question. <a href="/o/{offeringId}">Back to the course</a>.</p>
    </div>
  {:else if current}
    <div class="panes">
      <div class="render-pane">
        {#key current.id}
          <RenderFrame src={current.render_url} title="Submission by {current.netid}" height="100%" />
        {/key}
      </div>

      <aside class="side">
        <div class="who">
          <div>
            <strong>{current.display_name || current.netid}</strong>
            <span class="muted mono small">{current.netid}</span>
            <span class="sub muted small" title={fmtDateTime(current.submitted_at)}>
              attempt {current.attempt_no}, {fmtRelative(current.submitted_at)}{#if current.client?.env}, from {current.client.env}{/if}
            </span>
          </div>
          <div class="nav">
            <button onclick={prev} disabled={index === 0} title="Previous (k)">Prev</button>
            <span class="num small muted">{index + 1}/{items.length}</span>
            <button onclick={next} disabled={index >= items.length - 1} title="Next (j)">Next</button>
          </div>
        </div>

        {#if current.done}
          <Notice label="Graded">Score saved{current.score?.points != null ? `: ${trim(current.score.points)}` : ''}. You can change it and save again.</Notice>
        {:else if current.score?.auto_points != null}
          <p class="muted">The autograder gave <span class="num">{trim(current.score.auto_points)}</span> pts for the checked parts.</p>
        {/if}

        <form onsubmit={(e) => { e.preventDefault(); void submit(); }}>
          {#if rubric.length > 0}
            <table class="rubric">
              <tbody>
                {#each rubric as r (r.key)}
                  <tr>
                    <td class="wrap">
                      <label for="r-{r.key}">{r.title}</label>
                      {#if r.description}<span class="sub muted small">{r.description}</span>{/if}
                    </td>
                    <td class="num">
                      <input
                        id="r-{r.key}"
                        type="number"
                        min="0"
                        max={r.max_points}
                        step="0.5"
                        bind:value={rubricScores[r.key]}
                        onblur={() => clampRubric(r)}
                      />
                    </td>
                    <td class="muted num small">/ {trim(r.max_points)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}

          <label class="field">
            <span>
              Manual points
              {#if rubric.length > 0 && !manualTouched}<span class="muted">(sum of rubric)</span>{/if}
              {#if maxPoints !== null}<span class="muted">(up to {trim(maxPoints)})</span>{/if}
            </span>
            <input
              type="number"
              min="0"
              max={maxPoints ?? undefined}
              step="0.5"
              value={effectiveManual}
              oninput={(e) => {
                manualTouched = true;
                const v = (e.currentTarget as HTMLInputElement).value;
                manualPoints = v === '' ? null : Number(v);
              }}
            />
            {#if manualTouched && rubric.length > 0}
              <button type="button" class="quiet small" onclick={() => { manualTouched = false; manualPoints = null; }}>Use rubric sum</button>
            {/if}
          </label>

          <label class="field">
            <span>Feedback <span class="muted">(press f to jump here)</span></span>
            <textarea bind:this={feedbackEl} bind:value={feedback} rows="7" placeholder="What the student should take away from this attempt."></textarea>
          </label>

          <label class="field inline">
            <input type="checkbox" bind:checked={final} />
            <span>Release this grade to the student</span>
          </label>

          {#if flash}<p class="small" style="color:var(--accent)">{flash}</p>{/if}

          <div class="actions">
            <button type="submit" class="primary" disabled={submitting}>{submitting ? 'Saving' : current.done ? 'Save again' : 'Save score'}</button>
            <span class="muted small">
              <kbd>j</kbd> next, <kbd>k</kbd> previous, <kbd>⌘</kbd><kbd>Enter</kbd> saves
            </span>
          </div>
        </form>

        {#if current.outputs && Object.keys(current.outputs).length > 0}
          <section class="outputs">
            <h3>Submitted answers</h3>
            {#each Object.entries(current.outputs) as [key, value] (key)}
              <div class="output">
                <div class="output-key">{key}</div>
                <pre class="output-value">{typeof value === 'string' ? value : JSON.stringify(value, null, 2)}</pre>
              </div>
            {/each}
          </section>
        {/if}
        <p class="small muted history">
          <a href="/o/{offeringId}/students/{current.netid}">All submissions by {current.netid}</a>
        </p>
      </aside>
    </div>
  {/if}
</div>

<style>
  .queue {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: calc(100vh - var(--topbar-h));
  }
  .bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 20px;
    border-bottom: 1px solid var(--rule);
    font-size: 14px;
    flex-wrap: wrap;
  }
  .bar .left,
  .bar .right {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
  }
  .back {
    color: var(--ink);
  }
  .progress {
    font-weight: 600;
  }
  .pad {
    padding: 16px 20px;
  }
  .panes {
    flex: 1;
    display: grid;
    grid-template-columns: minmax(0, 1fr) 400px;
    min-height: 0;
  }
  .render-pane {
    min-height: 480px;
    height: calc(100vh - var(--topbar-h) - 42px);
    padding: 10px;
  }
  .render-pane :global(iframe.render),
  .render-pane :global(.pending) {
    height: 100% !important;
  }
  .side {
    border-left: 1px solid var(--rule);
    padding: 14px 16px 24px;
    overflow-y: auto;
    height: calc(100vh - var(--topbar-h) - 42px);
  }
  .who {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    align-items: flex-start;
    margin-bottom: 12px;
  }
  .who strong {
    display: block;
  }
  .who .sub {
    display: block;
  }
  .nav {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-shrink: 0;
  }
  .nav button {
    padding: 4px 8px;
    font-size: 12px;
  }
  table.rubric {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 12px;
    font-size: 14px;
  }
  table.rubric td {
    padding: 5px 4px;
    border-bottom: 1px solid var(--rule);
    vertical-align: middle;
  }
  table.rubric td.wrap {
    white-space: normal;
  }
  table.rubric td .sub {
    display: block;
  }
  table.rubric input {
    width: 64px;
  }
  button.small {
    font-size: 12px;
    padding: 2px 6px;
    align-self: flex-start;
  }
  .history {
    margin-top: 16px;
  }
  @media (max-width: 900px) {
    .panes {
      grid-template-columns: 1fr;
    }
    .render-pane,
    .side {
      height: auto;
    }
    .render-pane {
      height: 60vh;
    }
    .side {
      border-left: 0;
      border-top: 1px solid var(--rule);
    }
  }

  .outputs { margin-top: 1rem; }
  .outputs h3 { font-size: 15px; margin: 0 0 8px; }
  .output { margin-bottom: 0.6rem; }
  .output-key { font-family: var(--mono, ui-monospace, monospace); font-size: 0.8rem; color: var(--muted); }
  .output-value { white-space: pre-wrap; word-break: break-word; background: var(--surface, rgba(0,0,0,0.04)); border: 1px solid var(--rule); border-radius: 4px; padding: 0.5rem 0.65rem; margin: 0.2rem 0 0; font: inherit; font-size: 0.95rem; max-height: 18rem; overflow: auto; }
</style>
