<script lang="ts">
  import { onMount } from 'svelte';
  import {
    api,
    errorMessage,
    type Assignment,
    type AssignmentSettings,
    type Environment,
    type GradePolicy,
    type QuestionSpec,
    type VersionResponse,
  } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import { fmtDateTime, fmtPolicy, trim } from '$lib/format';
  import type { Params } from '$lib/router.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  const ENVIRONMENTS: Environment[] = ['molab', 'wasm', 'discovery'];
  const POLICIES: GradePolicy[] = ['latest', 'highest', 'first', 'selected'];

  let assignments = $state<Assignment[] | null>(null);
  let error = $state<string | null>(null);
  let message = $state<string | null>(null);
  let busy = $state(false);

  // New assignment form
  let showNew = $state(false);
  let newSlug = $state('');
  let newTitle = $state('');
  let newSettings = $state<SettingsForm>(blankSettings());

  // Edit settings (one assignment at a time)
  let editing = $state<string | null>(null);
  let editTitle = $state('');
  let editSettings = $state<SettingsForm>(blankSettings());

  // Version upload (one assignment at a time)
  let uploading = $state<string | null>(null);
  let instructorFiles = $state<FileList | null>(null);
  let studentFiles = $state<FileList | null>(null);
  let questionsJson = $state('');
  let cellHashesJson = $state('{}');
  let lastVersion = $state<VersionResponse | null>(null);

  // Export selection
  let exportIds = $state<Set<string>>(new Set());

  interface SettingsForm {
    due_at: string;
    attempts_allowed: number | null;
    grade_policy: GradePolicy;
    environments: Environment[];
    log_checks: boolean;
  }

  function blankSettings(): SettingsForm {
    return { due_at: '', attempts_allowed: null, grade_policy: 'latest', environments: ['molab', 'wasm'], log_checks: true };
  }

  function toForm(s: AssignmentSettings): SettingsForm {
    return {
      due_at: s.due_at ? toLocalInput(s.due_at) : '',
      attempts_allowed: s.attempts_allowed,
      grade_policy: s.grade_policy,
      environments: [...s.environments],
      log_checks: s.log_checks,
    };
  }

  function fromForm(f: SettingsForm): AssignmentSettings {
    return {
      due_at: f.due_at ? new Date(f.due_at).toISOString() : null,
      attempts_allowed: f.attempts_allowed === null || Number.isNaN(f.attempts_allowed) ? null : f.attempts_allowed,
      grade_policy: f.grade_policy,
      environments: f.environments,
      log_checks: f.log_checks,
    };
  }

  function toLocalInput(iso: string): string {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  function toggleEnv(form: SettingsForm, env: Environment) {
    form.environments = form.environments.includes(env)
      ? form.environments.filter((e) => e !== env)
      : [...form.environments, env];
  }

  async function load() {
    try {
      assignments = await api.offerings.assignments(offeringId);
    } catch (err) {
      error = errorMessage(err);
      assignments = [];
    }
  }
  onMount(load);

  async function run(label: string, fn: () => Promise<unknown>) {
    busy = true;
    error = null;
    message = null;
    try {
      await fn();
      message = label;
      await load();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  function createAssignment(e: SubmitEvent) {
    e.preventDefault();
    const slug = newSlug.trim();
    const title = newTitle.trim();
    const settings = fromForm(newSettings);
    void run(`Created ${slug}.`, async () => {
      await api.assignments.create(offeringId, { slug, title, settings });
      showNew = false;
      newSlug = '';
      newTitle = '';
      newSettings = blankSettings();
    });
  }

  function startEdit(a: Assignment) {
    editing = a.id;
    editTitle = a.title;
    editSettings = toForm(a.settings);
    uploading = null;
  }

  function saveEdit(e: SubmitEvent) {
    e.preventDefault();
    const id = editing;
    if (!id) return;
    const title = editTitle.trim();
    const settings = fromForm(editSettings);
    void run('Settings saved.', async () => {
      await api.assignments.patch(offeringId, id, { title, settings });
      editing = null;
    });
  }

  function startUpload(a: Assignment) {
    uploading = a.id;
    editing = null;
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

  function uploadVersion(e: SubmitEvent) {
    e.preventDefault();
    const id = uploading;
    const instructor_notebook = instructorFiles?.[0];
    const student_notebook = studentFiles?.[0];
    if (!id || !instructor_notebook || !student_notebook) return;
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
    void run('Version uploaded.', async () => {
      lastVersion = await api.assignments.uploadVersion(offeringId, id, {
        instructor_notebook,
        student_notebook,
        questions,
        cell_hashes,
      });
    });
  }

  function toggleExport(id: string) {
    const next = new Set(exportIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    exportIds = next;
  }
</script>

<div class="page-head">
  <div>
    <p class="eyebrow"><a href="/o/{offeringId}">{enrollment?.title ?? 'Course'}</a></p>
    <h1>Assignments</h1>
    <p class="eyebrow" style="margin-top:6px">Tick assignments to export their grades to Canvas.</p>
  </div>
  <div class="row">
    {#if exportIds.size > 0}
      <a class="btn" href={api.exports.canvasUrl(offeringId, [...exportIds])} data-native download>Export Canvas CSV ({exportIds.size})</a>
    {/if}
    <button class="primary" onclick={() => (showNew = !showNew)}>{showNew ? 'Cancel' : 'New assignment'}</button>
  </div>
</div>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}
{#if message}<Notice label="Done">{message}</Notice>{/if}

{#snippet settingsFields(form: SettingsForm)}
  <div class="settings-grid">
    <label class="field"><span>Due</span><input type="datetime-local" bind:value={form.due_at} /></label>
    <label class="field"><span>Attempts allowed <span class="muted">(blank = unlimited)</span></span><input type="number" min="1" step="1" bind:value={form.attempts_allowed} /></label>
    <label class="field">
      <span>Grade policy</span>
      <select bind:value={form.grade_policy}>
        {#each POLICIES as p (p)}<option value={p}>{fmtPolicy(p)}</option>{/each}
      </select>
    </label>
    <div class="field">
      <span>Environments</span>
      <div class="row">
        {#each ENVIRONMENTS as env (env)}
          <label class="small"><input type="checkbox" checked={form.environments.includes(env)} onchange={() => toggleEnv(form, env)} />{env}</label>
        {/each}
      </div>
    </div>
    <label class="field inline"><input type="checkbox" bind:checked={form.log_checks} /><span>Log check events</span></label>
  </div>
{/snippet}

{#if showNew}
  <form class="card block" onsubmit={createAssignment}>
    <h3>New assignment</h3>
    <div class="settings-grid">
      <label class="field"><span>Slug</span><input required bind:value={newSlug} placeholder="glm" pattern="[a-z0-9-]+" /></label>
      <label class="field"><span>Title</span><input required bind:value={newTitle} placeholder="General linear model" /></label>
    </div>
    {@render settingsFields(newSettings)}
    <div class="actions"><button class="primary" type="submit" disabled={busy}>Create</button></div>
  </form>
{/if}

{#if assignments === null}
  <Loading />
{:else if assignments.length === 0 && !showNew}
  <p class="empty">No assignments yet. The usual path is <code>grader publish</code> from the assignments repository, which creates the assignment and its first version. You can also create one here and upload a version by hand.</p>
{:else}
  {#each assignments as a (a.id)}
    <section class="block assignment">
      <div class="block-head">
        <h2>
          <label class="pick" title="Include in Canvas export"><input type="checkbox" checked={exportIds.has(a.id)} onchange={() => toggleExport(a.id)} /></label>
          {a.title} <span class="mono muted small">{a.slug}</span>
          <span class="muted small" style="font-weight:400">version {a.latest_version ?? 'none yet'}</span>
        </h2>
        <div class="row">
          <button class="quiet" onclick={() => (editing === a.id ? (editing = null) : startEdit(a))}>{editing === a.id ? 'Cancel' : 'Edit settings'}</button>
          <button class="quiet" onclick={() => (uploading === a.id ? (uploading = null) : startUpload(a))}>{uploading === a.id ? 'Cancel' : 'Upload version'}</button>
        </div>
      </div>

      <dl class="settings">
        <div><dt>Due</dt><dd>{a.settings.due_at ? fmtDateTime(a.settings.due_at) : 'no due date'}</dd></div>
        <div><dt>Attempts</dt><dd class="num">{a.settings.attempts_allowed ?? 'unlimited'}</dd></div>
        <div><dt>Policy</dt><dd>{fmtPolicy(a.settings.grade_policy)}</dd></div>
        <div><dt>Environments</dt><dd>{a.settings.environments.length > 0 ? a.settings.environments.join(', ') : 'none'}</dd></div>
        <div><dt>Check logging</dt><dd>{a.settings.log_checks ? 'on' : 'off'}</dd></div>
        <div><dt>Questions</dt><dd class="num">{a.questions.length}, {trim(a.questions.reduce((n, q) => n + q.max_points, 0))} pts</dd></div>
      </dl>

      {#if editing === a.id}
        <form class="card" onsubmit={saveEdit}>
          <label class="field"><span>Title</span><input required bind:value={editTitle} /></label>
          {@render settingsFields(editSettings)}
          <div class="actions"><button class="primary" type="submit" disabled={busy}>Save settings</button></div>
        </form>
      {/if}

      {#if uploading === a.id}
        <form class="card" onsubmit={uploadVersion}>
          <h3>Upload version {(a.latest_version ?? 0) + 1}</h3>
          <div class="settings-grid">
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
            {#if lastVersion}
              <span class="small">Version {lastVersion.version} · <a href={lastVersion.student_url} data-native>student notebook</a></span>
            {/if}
          </div>
        </form>
      {/if}

      {#if a.questions.length > 0}
        <div class="tablewrap">
          <table class="data">
            <thead><tr><th>Question</th><th>Title</th><th>Graded</th><th class="num">Points</th><th></th></tr></thead>
            <tbody>
              {#each [...a.questions].sort((x, y) => x.order - y.order) as q (q.id)}
                <tr>
                  <td class="mono">{q.qid}</td>
                  <td class="wrap">{q.title === q.qid ? '' : q.title}</td>
                  <td>{q.grading_mode === 'auto' ? 'automatically' : q.grading_mode === 'manual' ? 'by hand' : 'partly by hand'}</td>
                  <td class="num">{trim(q.max_points)}</td>
                  <td>{#if q.grading_mode !== 'auto'}<a class="small" href="/o/{offeringId}/grade/{q.id}">Grading queue</a>{/if}</td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {:else}
        <p class="empty">Questions appear once a version is published.</p>
      {/if}
    </section>
  {/each}
{/if}

<style>
  .settings-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0 16px;
  }
  dl.settings {
    display: flex;
    flex-wrap: wrap;
    gap: 6px 24px;
    margin: 0 0 14px;
    font-size: 14px;
  }
  dl.settings div {
    display: flex;
    gap: 6px;
  }
  dl.settings dt {
    color: var(--muted);
  }
  dl.settings dd {
    margin: 0;
  }
  .assignment .card {
    margin-bottom: 12px;
  }
  .pick input {
    margin-right: 4px;
  }
</style>
