<script lang="ts">
  import { onMount } from 'svelte';
  import {
    api,
    errorMessage,
    type Assignment,
    type QuestionSpec,
    type VersionResponse,
    type VersionSummary,
  } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import { blankSettings, fromForm, toForm } from '$lib/assignmentSettings';
  import { fmtDateTime, fmtPolicy, fmtRelative, trim } from '$lib/format';
  import type { Params } from '$lib/router.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import SettingsFields from '$lib/components/SettingsFields.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const assignmentId = $derived(params.assignment ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  let a = $state<Assignment | null>(null);
  let versions = $state<VersionSummary[]>([]);
  let loaded = $state(false);
  let error = $state<string | null>(null);
  let message = $state<string | null>(null);
  let busy = $state(false);

  let editing = $state(false);
  let editTitle = $state('');
  let editSettings = $state(blankSettings());

  // Hand upload: two notebooks plus the question list as JSON. `grader publish`
  // does all of this from the instructor notebook alone.
  let uploading = $state(false);
  let instructorFiles = $state<FileList | null>(null);
  let studentFiles = $state<FileList | null>(null);
  let questionsJson = $state('');
  let cellHashesJson = $state('{}');
  let lastVersion = $state<VersionResponse | null>(null);

  let copied = $state(false);

  async function load() {
    try {
      const [list, vs] = await Promise.all([
        api.offerings.assignments(offeringId),
        api.assignments.versions(offeringId, assignmentId),
      ]);
      a = list.find((x) => x.id === assignmentId) ?? null;
      versions = vs;
    } catch (err) {
      error = errorMessage(err);
    } finally {
      loaded = true;
    }
  }
  onMount(load);

  const base = $derived(a && enrollment ? `/a/${enrollment.course_slug}/${enrollment.term}/${a.slug}` : '');
  const launchUrl = $derived(base ? `${location.origin}${base}/launch` : '');
  const points = $derived(a ? a.questions.reduce((n, q) => n + q.max_points, 0) : 0);
  const questions = $derived(a ? [...a.questions].sort((x, y) => x.order - y.order) : []);

  function startEdit() {
    if (!a) return;
    editTitle = a.title;
    editSettings = toForm(a.settings);
    editing = true;
  }

  async function saveEdit(e: SubmitEvent) {
    e.preventDefault();
    if (!a) return;
    busy = true;
    error = null;
    message = null;
    try {
      await api.assignments.patch(offeringId, a.id, { title: editTitle.trim(), settings: fromForm(editSettings) });
      editing = false;
      message = 'Settings saved.';
      await load();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  async function copyLaunch() {
    try {
      await navigator.clipboard.writeText(launchUrl);
      copied = true;
      setTimeout(() => (copied = false), 1500);
    } catch {
      error = `Copy failed; the link is ${launchUrl}`;
    }
  }

  function startUpload() {
    if (!a) return;
    uploading = !uploading;
    lastVersion = null;
    instructorFiles = null;
    studentFiles = null;
    cellHashesJson = '{}';
    questionsJson = JSON.stringify(
      a.questions.length > 0
        ? a.questions.map((q) => ({ qid: q.qid, title: q.title, max_points: q.max_points, grading_mode: q.grading_mode, check_keys: [] }))
        : [{ qid: 'q01', title: 'Question 1', max_points: 5, grading_mode: 'auto', check_keys: [] }],
      null,
      2,
    );
  }

  async function uploadVersion(e: SubmitEvent) {
    e.preventDefault();
    const instructor_notebook = instructorFiles?.[0];
    const student_notebook = studentFiles?.[0];
    if (!a || !instructor_notebook || !student_notebook) return;
    let questions: QuestionSpec[];
    let cell_hashes: Record<string, string>;
    try {
      questions = JSON.parse(questionsJson) as QuestionSpec[];
      if (!Array.isArray(questions)) throw new Error('questions must be a JSON array');
      cell_hashes = JSON.parse(cellHashesJson || '{}') as Record<string, string>;
    } catch (err) {
      error = `Invalid JSON: ${errorMessage(err)}`;
      return;
    }
    busy = true;
    error = null;
    try {
      lastVersion = await api.assignments.uploadVersion(offeringId, a.id, { instructor_notebook, student_notebook, questions, cell_hashes });
      message = `Version ${lastVersion.version} published.`;
      await load();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  function graded(mode: string): string {
    return mode === 'auto' ? 'automatically' : mode === 'manual' ? 'by hand' : 'partly by hand';
  }
</script>

{#if !loaded}
  <Loading />
{:else if !a}
  <Notice kind="warn" label="Not found">No such assignment. <a href="/o/{offeringId}/assignments">Back to assignments</a>.</Notice>
{:else}
  <div class="page-head">
    <div>
      <p class="eyebrow"><a href="/o/{offeringId}/assignments">Assignments</a></p>
      <h1>{a.title} <span class="mono muted small">{a.slug}</span></h1>
      <p class="eyebrow">
        <span class="chip">{a.availability?.state ?? 'open'}</span>
        {a.settings.visibility === 'enrolled' ? 'enrolled students only' : 'public'},
        version {a.latest_version ?? 'none yet'}, {questions.length} {questions.length === 1 ? 'question' : 'questions'}, {trim(points)} pts
      </p>
    </div>
    <div class="row">
      <button onclick={() => (editing ? (editing = false) : startEdit())} aria-expanded={editing}>{editing ? 'Close settings' : 'Settings'}</button>
    </div>
  </div>

  {#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}
  {#if message}<Notice label="Done">{message}</Notice>{/if}

  {#if editing}
    <form class="card block" onsubmit={saveEdit}>
      <label class="field"><span>Title</span><input required bind:value={editTitle} /></label>
      <SettingsFields bind:form={editSettings} />
      <div class="actions">
        <button class="primary" type="submit" disabled={busy}>Save settings</button>
        <button class="quiet" type="button" onclick={() => (editing = false)}>Cancel</button>
      </div>
    </form>
  {/if}

  <section class="block">
    <dl class="settings">
      <div><dt>Opens</dt><dd>{a.settings.release_at ? fmtDateTime(a.settings.release_at) : a.settings.visibility === 'enrolled' ? 'not set (hidden from students)' : 'always open'}</dd></div>
      <div><dt>Due</dt><dd>{a.settings.due_at ? fmtDateTime(a.settings.due_at) : 'no due date'}{a.settings.late_policy === 'reject' ? ', no late work' : ', late work accepted'}</dd></div>
      <div><dt>Closes</dt><dd>{a.settings.close_at ? fmtDateTime(a.settings.close_at) : 'never'}</dd></div>
      <div><dt>Grading</dt><dd>autograde {a.settings.autograde === false ? 'off' : 'on'}, re-run {a.settings.render === false ? 'off' : 'on'}{a.settings.notebook_submission ? `, whole notebook ${trim(a.settings.notebook_points ?? 0)} pts` : ''}</dd></div>
      <div><dt>Attempts</dt><dd>{a.settings.attempts_allowed ?? 'unlimited'}, {fmtPolicy(a.settings.grade_policy)}</dd></div>
      <div><dt>Environments</dt><dd>{a.settings.environments.length > 0 ? a.settings.environments.join(', ') : 'none'}</dd></div>
    </dl>
    {#if base && a.latest_version !== null}
      <div class="links row">
        <a class="btn small" href="{base}/student.py" download="{a.slug}.py" data-native>Student notebook</a>
        <a class="btn small" href="{base}/molab" target="_blank" rel="noopener" data-native>Open in molab</a>
        <button class="small" onclick={copyLaunch} title={launchUrl}>{copied ? 'Copied' : 'Copy launch link'}</button>
        <span class="muted small">The launch link signs a student in and opens their portal on this assignment.</span>
      </div>
    {/if}
  </section>

  <section class="block">
    <h2>Questions</h2>
    {#if questions.length === 0}
      <p class="empty">Questions appear once a version is published.</p>
    {:else}
      <div class="tablewrap">
        <table class="data">
          <thead><tr><th>Question</th><th>Title</th><th>Graded</th><th class="num">Points</th><th></th></tr></thead>
          <tbody>
            {#each questions as q (q.id)}
              <tr>
                <td class="mono">{q.qid}</td>
                <td class="wrap">{q.title === q.qid ? '' : q.title}</td>
                <td>{graded(q.grading_mode)}</td>
                <td class="num">{trim(q.max_points)}</td>
                <td>{#if q.grading_mode !== 'auto'}<a class="small" href="/o/{offeringId}/grade/{q.id}">Grading queue</a>{/if}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>

  <section class="block">
    <div class="block-head">
      <h2>Versions</h2>
      <button class="quiet small" onclick={startUpload} aria-expanded={uploading}>{uploading ? 'Cancel' : 'Upload a version by hand'}</button>
    </div>
    <p class="muted small">Publish new versions with <code>grader publish {a.slug}.py --slug {a.slug}</code> from the assignments repository: it builds the student copy and the question list from the instructor notebook.</p>

    {#if uploading}
      <form class="card" onsubmit={uploadVersion}>
        <h3>Upload version {(a.latest_version ?? 0) + 1}</h3>
        <div class="pair">
          <label class="field"><span>Instructor notebook (.py)</span><input type="file" accept=".py" bind:files={instructorFiles} required /></label>
          <label class="field"><span>Student notebook (.py)</span><input type="file" accept=".py" bind:files={studentFiles} required /></label>
        </div>
        <label class="field">
          <span>Questions <span class="muted">JSON: [{'{'}qid, title, max_points, grading_mode, check_keys{'}'}]</span></span>
          <textarea class="mono" rows="8" bind:value={questionsJson} spellcheck="false"></textarea>
        </label>
        <label class="field">
          <span>Cell hashes <span class="muted">JSON object, from the release tool</span></span>
          <textarea class="mono" rows="3" bind:value={cellHashesJson} spellcheck="false"></textarea>
        </label>
        <div class="actions">
          <button class="primary" type="submit" disabled={busy || !instructorFiles?.length || !studentFiles?.length}>{busy ? 'Uploading' : 'Upload'}</button>
        </div>
      </form>
    {/if}

    {#if versions.length === 0}
      <p class="empty">No version published yet.</p>
    {:else}
      <div class="tablewrap">
        <table class="data">
          <thead><tr><th class="num">Version</th><th>Published</th><th>By</th><th>Questions</th><th></th></tr></thead>
          <tbody>
            {#each versions as v (v.id)}
              <tr>
                <td class="num">{v.version}</td>
                <td title={fmtDateTime(v.created_at)}>{fmtRelative(v.created_at)}</td>
                <td class="mono">{v.published_by ?? '—'}</td>
                <td class="wrap mono small">{v.questions.join(', ') || '—'}</td>
                <td><a class="small" href={v.student_url} download="{a.slug}-v{v.version}.py" data-native>Student copy</a></td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
{/if}

<style>
  dl.settings {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
    gap: 8px 24px;
    margin: 0 0 14px;
    font-size: 14px;
  }
  dl.settings dt {
    color: var(--muted);
    font-size: 12px;
  }
  dl.settings dd {
    margin: 0;
  }
  .links {
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }
  .pair {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0 16px;
  }
  h2 {
    font-size: 17px;
    margin: 0 0 8px;
  }
</style>
