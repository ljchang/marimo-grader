<script lang="ts">
  import { onDestroy, onMount, tick } from 'svelte';
  import {
    api,
    errorMessage,
    type Assignment,
    type Question,
    type RubricItem,
    type ScoreInput,
    type Submission,
  } from '$lib/api';
  import { DraftSaver, readBackup, type SaveStatus } from '$lib/draftSaver';
  import { auth } from '$lib/auth.svelte';
  import { subscribeEvents, type StreamState } from '$lib/events';
  import { fmtDateTime, fmtRelative, trim } from '$lib/format';
  import { router, type Params } from '$lib/router.svelte';
  import { groupRubric } from '$lib/rubricText';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import SubmissionView from '$lib/components/SubmissionView.svelte';
  import Splitter from '$lib/components/Splitter.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const questionId = $derived(params.questionId ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  // Width of the grading column; the notebook takes the rest. Dragged, kept per browser.
  const SIDE_W = 400;
  let sideW = $state<number | null>(SIDE_W);

  type Item = Submission;

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
  let publishing = $state(false);
  /** False for a TA in a course that reserves publishing for instructors. */
  let canPublish = $state(true);
  /** Publish-all, asked and waiting for a yes. */
  let confirmingAll = $state(false);
  let publishingAll = $state(false);
  let message = $state<string | null>(null);
  /** The submission whose form came back from this browser's backup, not the server. */
  let restored = $state<string | null>(null);

  // Every edit is a draft, saved as the grader goes; Publish is what the student sees.
  let statuses = $state<Record<string, SaveStatus>>({});
  const saver = new DraftSaver(
    (id, body, keepalive) => api.grading.score(id, body, { keepalive }),
    (id, st) => {
      statuses[id] = st;
      if (st.kind === 'saved') takeScore(st.sub);
    },
  );
  /** The form as last loaded or saved; an edit is anything that differs from it. */
  let baseline = '';

  let feedbackEl = $state<HTMLTextAreaElement | null>(null);

  const current = $derived(items[index] ?? null);
  const rubric = $derived<RubricItem[]>(current?.rubric ?? question?.rubric ?? []);
  const maxPoints = $derived(current?.max_points ?? question?.max_points ?? null);
  const isPublished = (it: Item) => !!it.score?.published_at;
  const doneCount = $derived(items.filter(isPublished).length);
  const rubricGroups = $derived(groupRubric(rubric));
  const blanks = $derived(rubric.filter((r) => rubricScores[r.key] == null).length);
  const rubricSum = $derived(
    rubric.reduce((sum, r) => sum + (rubricScores[r.key] ?? 0), 0),
  );
  const effectiveManual = $derived(
    manualTouched || rubric.length === 0 ? manualPoints : rubricSum,
  );

  /** What the form says, as the server takes it (scores clamped to their range). */
  const body = $derived.by<ScoreInput>(() => {
    const rubric_scores: Record<string, number> = {};
    for (const r of rubric) {
      const v = rubricScores[r.key];
      if (v != null && Number.isFinite(v)) rubric_scores[r.key] = Math.max(0, Math.min(r.max_points, v));
    }
    return { manual_points: effectiveManual, rubric_scores, feedback, final: false };
  });

  const status = $derived(current ? statuses[current.id] : undefined);
  const unsaved = $derived(status?.kind === 'saving' || status?.kind === 'error');
  const sc = $derived(current?.score ?? null);
  const hasDraft = $derived(!!sc?.draft);
  const draftCount = $derived(items.filter((it) => it.score?.draft).length);

  /** Hand the form to the autosave if it changed. */
  function noteEdit() {
    const id = current?.id;
    const json = JSON.stringify(body);
    if (!id || json === baseline) return;
    baseline = json;
    saver.edit(id, body);
  }

  // Any change to the form autosaves it as a draft. The effect runs a tick after the
  // change; anything that must see the latest form calls noteEdit() itself.
  $effect(noteEdit);

  function setForm(v: { manual_points?: number | null; rubric_scores?: Record<string, number>; feedback?: string | null } | null) {
    const scores: Record<string, number | null> = {};
    for (const r of rubric) scores[r.key] = v?.rubric_scores?.[r.key] ?? null;
    rubricScores = scores;
    manualPoints = v?.manual_points ?? null;
    const sum = rubric.reduce((s, r) => s + (scores[r.key] ?? 0), 0);
    // A total typed over the rubric sum stays an override when it comes back.
    manualTouched = manualPoints != null && (rubric.length === 0 || Math.abs(manualPoints - sum) > 1e-9);
    feedback = v?.feedback ?? '';
  }

  function resetForm(item: Item | null) {
    setForm(item?.score ?? null);
    const fromServer = JSON.stringify(body);
    // Edits this browser made that never reached the server (offline, a closed tab,
    // a crash) come back, and the autosave sends them on.
    const backup = item ? readBackup(item.id) : null;
    restored = null;
    if (item && backup) {
      setForm(backup);
      if (JSON.stringify(body) !== fromServer) restored = item.id;
    }
    baseline = restored ? '' : JSON.stringify(body);
  }

  /** A save answered: keep the score it returned, without touching the form. */
  function takeScore(sub: Submission) {
    items = items.map((it) => (it.id === sub.id ? { ...it, score: sub.score, status: sub.status } : it));
  }

  function go(to: number) {
    if (items.length === 0) return;
    // Whatever is waiting for the student being left goes now, not on a timer.
    if (current) {
      noteEdit();
      void saver.flush(current.id);
    }
    index = Math.max(0, Math.min(items.length - 1, to));
    pendingNew = 0;
    resetForm(items[index] ?? null);
  }

  function next() {
    // Prefer the next unpublished item; otherwise just step forward.
    const after = items.findIndex((it, i) => i > index && !isPublished(it));
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
      items = queue.items;
      canPublish = queue.can_publish;
      // A mark on the assignment page opens one student's answer.
      const netid = router.query.get('netid');
      index = Math.max(0, netid ? items.findIndex((s) => s.netid === netid) : 0);
      resetForm(items[index] ?? null);
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
        items = [...items, ...fresh];
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

  onDestroy(() => {
    unsubscribe?.();
    saver.flushAll();
    saver.dispose();
  });

  /** Closing the tab or reloading: send what is waiting, and warn if it might not land. */
  function onBeforeUnload(e: BeforeUnloadEvent) {
    saver.flushAll(true);
    if (saver.hasUnsaved()) e.preventDefault();
  }

  /** Publish every draft on this question; edits still on their way go first. */
  async function publishAll() {
    if (publishingAll) return;
    publishingAll = true;
    error = null;
    try {
      noteEdit();
      await saver.settle();
      const r = await api.grading.publishDrafts(offeringId, questionId);
      await refreshScores();
      message = `Published ${r.published} ${r.published === 1 ? 'draft' : 'drafts'}. Those students can see their scores and feedback now.`;
    } catch (err) {
      error = errorMessage(err);
    } finally {
      publishingAll = false;
      confirmingAll = false;
    }
  }

  /** Take the server's scores for every item, keeping the grader's place and form. */
  async function refreshScores() {
    const queue = await api.grading.queue(offeringId, questionId);
    const byId = new Map(queue.items.map((s) => [s.id, s]));
    items = items.map((it) => {
      const s = byId.get(it.id);
      return s ? { ...it, score: s.score, status: s.status } : it;
    });
  }

  /** Publish this student's grade, then move on. Already published, unchanged, or not
   *  ours to publish: just move on (the draft is saved either way). */
  async function publish() {
    const item = current;
    if (!item || publishing) return;
    if (!canPublish || (sc?.is_final && !unsaved)) {
      next();
      return;
    }
    publishing = true;
    error = null;
    try {
      takeScore(await saver.publish(item.id, body));
      restored = null;
      await tick();
      next();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      publishing = false;
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
      void publish();
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

  /** Start from full marks and take points off. */
  function fillBlanks() {
    for (const r of rubric) if (rubricScores[r.key] == null) rubricScores[r.key] = r.max_points;
  }

  function clampRubric(r: RubricItem) {
    const v = rubricScores[r.key];
    if (v === null || v === undefined) return;
    rubricScores[r.key] = Math.max(0, Math.min(r.max_points, v));
  }
</script>

<svelte:window onkeydown={onKey} onbeforeunload={onBeforeUnload} onpagehide={() => saver.flushAll(true)} />

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
      <span class="progress num">{doneCount} of {items.length} published{#if draftCount > 0}<span class="muted">, {draftCount} {draftCount === 1 ? 'draft' : 'drafts'}</span>{/if}</span>
      {#if canPublish && draftCount > 0 && !confirmingAll}
        <button class="small" onclick={() => { confirmingAll = true; message = null; }}>Publish all drafts</button>
      {/if}
    </div>
  </header>

  {#if confirmingAll}
    <div class="confirm" role="alertdialog" aria-label="Publish all drafts">
      <span>
        Publish {draftCount} {draftCount === 1 ? 'draft' : 'drafts'}? Those students will see their scores and feedback.
        Answers nobody has started stay unpublished.
      </span>
      <button class="primary small" onclick={publishAll} disabled={publishingAll}>{publishingAll ? 'Publishing…' : `Publish ${draftCount}`}</button>
      <button class="quiet small" onclick={() => (confirmingAll = false)} disabled={publishingAll}>Cancel</button>
    </div>
  {/if}
  {#if message}<div class="pad"><Notice label="Done">{message}</Notice></div>{/if}

  {#if error}<div class="pad"><Notice kind="error" label="Error">{error}</Notice></div>{/if}

  {#if loading}
    <div class="pad"><Loading label="Loading queue" /></div>
  {:else if items.length === 0}
    <div class="pad">
      <p class="empty">Nothing is waiting for a grade on this question. <a href="/o/{offeringId}">Back to the course</a>.</p>
    </div>
  {:else if current}
    <div class="panes" style:--side-w="{sideW ?? SIDE_W}px">
      <div class="render-pane">
        {#key current.id}
          <SubmissionView submission={current} resizable />
        {/key}
      </div>

      <Splitter
        bind:value={sideW}
        initial={SIDE_W}
        min={280}
        max={() => Math.max(280, window.innerWidth - 420)}
        invert
        storageKey="grader.sideWidth"
        label="Resize the grading panel"
      />

      <aside class="side">
        <div class="who">
          <div>
            <strong>{current.display_name || current.netid}</strong>
            <span class="muted mono small">{current.netid}</span>
            <span class="sub muted small" title={fmtDateTime(current.submitted_at)}>
              attempt {current.attempt_no}, {fmtRelative(current.submitted_at)}{#if current.client?.env}, from {current.client.env}{/if}
            </span>
            {#if current.render_info?.source === 'snapshot' && current.render_info.snapshot !== 'attached'}
              <!-- Next to the score: this is what the student saw, not a re-run. -->
              <span class="sub small">Graded from the student's own outputs{#if current.render_info.matched != null && current.render_info.total != null}{` (${current.render_info.matched}/${current.render_info.total} cells)`}{/if}</span>
            {/if}
          </div>
          <div class="nav">
            <button onclick={prev} disabled={index === 0} title="Previous (k)">Prev</button>
            <span class="num small muted">{index + 1}/{items.length}</span>
            <button onclick={next} disabled={index >= items.length - 1} title="Next (j)">Next</button>
          </div>
        </div>

        {#if restored === current.id}
          <Notice label="Restored">Edits from this browser that hadn't reached the server are back, and saved as a draft.</Notice>
        {/if}
        {#if current.score?.auto_points != null}
          <p class="muted">The autograder gave <span class="num">{trim(current.score.auto_points)}</span> pts for the checked parts.</p>
        {/if}

        <form onsubmit={(e) => { e.preventDefault(); void publish(); }}>
          {#if rubric.length > 0}
            <!-- Stays put when there is nothing left to fill, so the rows below don't jump. -->
            <button type="button" class="quiet small fill" onclick={fillBlanks} disabled={blanks === 0}>
              Full marks for the {blanks === rubric.length || blanks === 0 ? '' : `${blanks} `}blank {blanks === 1 ? 'item' : 'items'}
            </button>
            <table class="rubric">
              {#each rubricGroups as g, gi (gi)}
              <tbody>
                {#if g.label && !(g.items.length === 1 && g.items[0]?.title === g.label)}
                  <tr class="part">
                    <th colspan="2">{g.label}</th>
                    <td class="num">{trim(g.items.reduce((sum, r) => sum + (rubricScores[r.key] ?? 0), 0))}</td>
                    <td class="muted num small">/ {trim(g.total)}</td>
                  </tr>
                {/if}
                {#each g.items as r (r.key)}
                  <tr>
                    <td class="mono muted small key">{r.key}</td>
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
              {/each}
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

          <p class="save-state small" class:warn={status?.kind === 'error'} aria-live="polite">
            {#if status?.kind === 'saving'}
              Saving draft…
            {:else if status?.kind === 'error'}
              Not saved: {status.message}. {status.retrying ? 'Kept in this browser; trying again shortly.' : 'Kept in this browser; your next edit tries again.'}
            {:else if sc?.is_final}
              <span class="dot pub"></span>Published {fmtRelative(sc.graded_at)}. The student sees this.
            {:else if hasDraft && sc?.published_at}
              <span class="dot"></span>Draft saved {fmtRelative(sc.graded_at)}. The student still sees what was published {fmtRelative(sc.published_at)}.
            {:else if hasDraft}
              <span class="dot"></span>Draft saved {fmtRelative(sc?.graded_at)}. The student can't see it until {canPublish ? 'you publish' : 'an instructor publishes it'}.
            {:else if canPublish}
              <span class="muted">Edits save as a draft as you go. The student sees nothing until you publish.</span>
            {:else}
              <span class="muted">Edits save as a draft as you go. In this course an instructor publishes grades.</span>
            {/if}
          </p>

          <div class="actions">
            {#if canPublish}
              <button type="submit" class="primary" disabled={publishing || (!!sc?.is_final && !unsaved)}>
                {publishing ? 'Publishing…' : sc?.is_final && !unsaved ? 'Published' : sc?.published_at ? 'Publish changes' : 'Publish'}
              </button>
              <span class="muted small">
                <kbd>⌘</kbd><kbd>Enter</kbd> publishes and moves on, <kbd>j</kbd> next, <kbd>k</kbd> previous
              </span>
            {:else}
              <button type="submit">Next</button>
              <span class="muted small">
                <kbd>⌘</kbd><kbd>Enter</kbd> or <kbd>j</kbd> next, <kbd>k</kbd> previous
              </span>
            {/if}
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
    grid-template-columns: minmax(0, 1fr) auto var(--side-w, 400px);
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
  table.rubric .part th,
  table.rubric .part td {
    padding-top: 14px;
    text-align: left;
    font-weight: 600;
  }
  table.rubric .part td {
    white-space: nowrap;
  }
  table.rubric .part td.num {
    text-align: right;
  }
  table.rubric td.key {
    width: 2.5em;
    padding-right: 6px;
  }
  button.fill {
    margin-bottom: 6px;
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
  .confirm {
    display: flex;
    align-items: center;
    gap: 10px;
    flex-wrap: wrap;
    padding: 10px 20px;
    border-bottom: 1px solid var(--rule);
    background: var(--accent-soft);
    font-size: 14px;
  }
  .confirm span {
    flex: 1;
    min-width: 240px;
  }
  .save-state {
    min-height: 2.6em;
    margin: 4px 0 8px;
    color: var(--ink);
  }
  .save-state.warn {
    color: var(--warn);
    font-weight: 600;
  }
  .dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    margin-right: 6px;
    border-radius: 50%;
    border: 1.5px solid var(--muted);
    vertical-align: 1px;
  }
  .dot.pub {
    background: var(--accent);
    border-color: var(--accent);
  }
  @media (max-width: 900px) {
    .panes {
      grid-template-columns: 1fr;
    }
    .panes > :global(.splitter) {
      display: none;
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
