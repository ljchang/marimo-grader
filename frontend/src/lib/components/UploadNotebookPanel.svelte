<script lang="ts">
  // Replace an assignment's notebook with a corrected instructor copy. The
  // questions come from the notebook, so this is also how one is added or
  // changed. Nothing is published until the instructor has read what would change.
  import { api, errorMessage, type Assignment, type VersionPreview } from '$lib/api';
  import { uploadLabel } from '$lib/assignmentView';
  import { trim } from '$lib/format';
  import Drawer from './Drawer.svelte';
  import Notice from './Notice.svelte';

  let {
    offeringId,
    assignment,
    onclose,
    onpublished,
  }: {
    offeringId: string;
    assignment: Assignment;
    onclose: () => void;
    onpublished: (message: string) => void;
  } = $props();

  let files = $state<FileList | null>(null);
  let preview = $state<VersionPreview | null>(null);
  let reading = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);
  let studentUrl = $state<string | null>(null);

  // A preview is fetched as soon as a file is chosen.
  $effect(() => {
    const file = files?.[0];
    if (!file) return;
    preview = null;
    error = null;
    reading = true;
    api.assignments
      .previewVersion(offeringId, assignment.id, file)
      .then((p) => (preview = p))
      .catch((err) => (error = errorMessage(err)))
      .finally(() => (reading = false));
  });

  $effect(() => {
    const text = preview?.student_notebook;
    if (!text) {
      studentUrl = null;
      return;
    }
    const href = URL.createObjectURL(new Blob([text], { type: 'text/x-python' }));
    studentUrl = href;
    return () => URL.revokeObjectURL(href);
  });

  async function publish() {
    const file = files?.[0];
    if (!file || !preview) return;
    busy = true;
    error = null;
    try {
      const v = await api.assignments.publishFromNotebook(offeringId, assignment.id, file);
      onpublished(v.unchanged ? `Nothing changed: students already have this notebook.` : `Published. Students now get the corrected notebook (version ${v.version}).`);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  const graded = (mode: string | undefined) => (mode === 'manual' ? 'by hand' : mode === 'hybrid' ? 'partly by hand' : 'automatically');
</script>

<Drawer title={uploadLabel(assignment).replace('…', '')} subtitle={assignment.title} {onclose}>
  <p class="lead">
    Choose the instructor notebook: the one with solutions and the <code>_marks</code> cell. The grader builds the student copy
    from it and reads the questions from <code>_marks</code>. You'll see what changes before anything is published.
  </p>
  <input type="file" accept=".py" bind:files aria-label="Instructor notebook" />

  {#if reading}<p class="muted small">Reading the notebook…</p>{/if}
  {#if error}<Notice kind="error" label="Can't publish this notebook">{error}</Notice>{/if}

  {#if preview}
    {#if preview.unchanged}
      <Notice label="No changes">Students already have this notebook and these questions.</Notice>
    {:else}
      <h3>What changes</h3>
      <ul class="changes">
        {#each preview.added as q (q)}<li><span class="add">Adds</span> <span class="mono">{q}</span></li>{/each}
        {#each preview.removed as q (q)}<li><span class="rm">Removes</span> <span class="mono">{q}</span> <span class="muted">(answers already submitted are kept)</span></li>{/each}
        {#each preview.changed as c (c.qid)}<li><span class="chg">Changes</span> <span class="mono">{c.qid}</span>: {c.what.join(', ')}</li>{/each}
        {#if preview.added.length + preview.removed.length + preview.changed.length === 0}
          <li class="muted">Same questions; only the notebook text changed.</li>
        {/if}
      </ul>
    {/if}

    <h3>Questions</h3>
    <ul class="qs">
      {#each preview.questions as q (q.qid)}
        <li><span class="mono">{q.qid}</span> {q.title === q.qid ? '' : q.title}<span class="muted small">{trim(q.max_points)} points, graded {graded(q.grading_mode)}</span></li>
      {:else}
        <li class="muted">No questions; students submit the whole notebook.</li>
      {/each}
    </ul>
    {#if studentUrl}<p class="small"><a href={studentUrl} download="{assignment.slug}_student.py" data-native>Download the student copy</a> to check what students will see.</p>{/if}
  {/if}

  {#snippet footer()}
    <button class="primary" onclick={publish} disabled={busy || !preview || preview.unchanged}>{busy ? 'Publishing…' : 'Publish'}</button>
    <button class="quiet" onclick={onclose}>Cancel</button>
  {/snippet}
</Drawer>

<style>
  .lead {
    margin: 16px 0 12px;
    font-size: 14px;
  }
  h3 {
    font-size: 15px;
    margin: 18px 0 6px;
  }
  ul {
    list-style: none;
    margin: 0;
    padding: 0;
    font-size: 14px;
  }
  li {
    padding: 4px 0;
  }
  .qs li .small {
    display: block;
  }
  .add {
    color: var(--accent);
    font-weight: 600;
  }
  .rm {
    color: var(--danger);
    font-weight: 600;
  }
  .chg {
    color: var(--warn);
    font-weight: 600;
  }
</style>
