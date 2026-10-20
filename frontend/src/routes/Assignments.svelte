<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, type Assignment } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import { blankSettings, fromForm } from '$lib/assignmentSettings';
  import { fmtDateTime, trim } from '$lib/format';
  import type { Params } from '$lib/router.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import SettingsFields from '$lib/components/SettingsFields.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  let assignments = $state<Assignment[] | null>(null);
  let error = $state<string | null>(null);
  let message = $state<string | null>(null);
  let busy = $state(false);

  let showNew = $state(false);
  let newSlug = $state('');
  let newTitle = $state('');
  let newSettings = $state(blankSettings());

  // Rows are selected by clicking them; the selection is what Export takes.
  let selected = $state<Set<string>>(new Set());

  type Key = 'title' | 'access' | 'status' | 'opens' | 'due' | 'closes' | 'version' | 'questions' | 'points' | 'grading';
  let sortKey = $state<Key>('due');
  let sortDir = $state<1 | -1>(1);

  const COLUMNS: { key: Key; label: string; num?: boolean }[] = [
    { key: 'title', label: 'Assignment' },
    { key: 'access', label: 'Access' },
    { key: 'status', label: 'Status' },
    { key: 'opens', label: 'Opens' },
    { key: 'due', label: 'Due' },
    { key: 'closes', label: 'Closes' },
    { key: 'version', label: 'Version', num: true },
    { key: 'questions', label: 'Questions', num: true },
    { key: 'points', label: 'Points', num: true },
    { key: 'grading', label: 'Grading' },
  ];

  const STATE_ORDER: Record<string, number> = { open: 0, upcoming: 1, closed: 2 };

  const points = (a: Assignment) => a.questions.reduce((n, q) => n + q.max_points, 0);

  function grading(a: Assignment): string {
    if (a.settings.notebook_submission) return 'whole notebook';
    if (a.settings.autograde === false) return 'by hand';
    const modes = new Set(a.questions.map((q) => q.grading_mode));
    if (modes.size === 0) return '—';
    if (modes.size === 1 && modes.has('auto')) return 'auto';
    if (!modes.has('auto')) return 'by hand';
    return 'auto + by hand';
  }

  function value(a: Assignment, key: Key): string | number | null {
    switch (key) {
      case 'title': return a.title.toLowerCase();
      case 'access': return a.settings.visibility === 'enrolled' ? 1 : 0;
      case 'status': return STATE_ORDER[a.availability?.state ?? 'open'] ?? 0;
      case 'opens': return a.settings.release_at ?? null;
      case 'due': return a.settings.due_at ?? null;
      case 'closes': return a.settings.close_at ?? null;
      case 'version': return a.latest_version;
      case 'questions': return a.questions.length;
      case 'points': return points(a);
      case 'grading': return grading(a);
    }
  }

  const rows = $derived.by(() => {
    const list = [...(assignments ?? [])];
    return list.sort((x, y) => {
      const a = value(x, sortKey);
      const b = value(y, sortKey);
      // Blanks (no due date, no version) sort last whichever way the column runs.
      if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
      return (a < b ? -1 : a > b ? 1 : 0) * sortDir;
    });
  });

  function sortBy(key: Key) {
    if (key === sortKey) sortDir = sortDir === 1 ? -1 : 1;
    else {
      sortKey = key;
      sortDir = 1;
    }
  }

  function toggle(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected = next;
  }

  function onRowClick(e: MouseEvent, id: string) {
    // The title link drills down; everything else on the row selects it.
    if ((e.target as HTMLElement).closest('a, button, input, label')) return;
    toggle(id);
  }

  const allSelected = $derived(rows.length > 0 && rows.every((a) => selected.has(a.id)));
  function selectAll() {
    selected = allSelected ? new Set() : new Set(rows.map((a) => a.id));
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

  async function createAssignment(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = null;
    message = null;
    const slug = newSlug.trim();
    try {
      await api.assignments.create(offeringId, { slug, title: newTitle.trim(), settings: fromForm(newSettings) });
      message = `Created ${slug}.`;
      showNew = false;
      newSlug = '';
      newTitle = '';
      newSettings = blankSettings();
      await load();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  const statusLabel = (a: Assignment) => a.availability?.state ?? 'open';
</script>

<div class="page-head">
  <div>
    <p class="eyebrow"><a href="/o/{offeringId}">{enrollment?.title ?? 'Course'}</a></p>
    <h1>Assignments</h1>
  </div>
  <div class="row">
    <button class="primary" onclick={() => (showNew = !showNew)}>{showNew ? 'Cancel' : 'New assignment'}</button>
  </div>
</div>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}
{#if message}<Notice label="Done">{message}</Notice>{/if}

{#if showNew}
  <form class="card block" onsubmit={createAssignment}>
    <h3>New assignment</h3>
    <p class="muted small">The usual path is <code>grader publish</code> from the assignments repository, which creates the assignment and its first version together.</p>
    <div class="pair">
      <label class="field"><span>Slug</span><input required bind:value={newSlug} placeholder="glm" pattern="[a-z0-9-]+" /></label>
      <label class="field"><span>Title</span><input required bind:value={newTitle} placeholder="General linear model" /></label>
    </div>
    <SettingsFields bind:form={newSettings} />
    <div class="actions"><button class="primary" type="submit" disabled={busy}>Create</button></div>
  </form>
{/if}

{#if assignments === null}
  <Loading />
{:else if assignments.length === 0 && !showNew}
  <p class="empty">No assignments yet. The usual path is <code>grader publish</code> from the assignments repository, which creates the assignment and its first version.</p>
{:else if assignments.length > 0}
  <div class="toolbar" role="toolbar" aria-label="Selection">
    <span class="muted small">{selected.size > 0 ? `${selected.size} selected` : 'Click rows to select them'}</span>
    <button class="quiet small" onclick={selectAll}>{allSelected ? 'Clear selection' : 'Select all'}</button>
    {#if selected.size > 0}
      <a class="btn small" href={api.exports.canvasUrl(offeringId, [...selected])} data-native download>Export Canvas CSV ({selected.size})</a>
    {/if}
  </div>
  <div class="tablewrap">
    <table class="data assignments">
      <thead>
        <tr>
          <th class="pick"><input type="checkbox" aria-label="Select all" checked={allSelected} indeterminate={selected.size > 0 && !allSelected} onchange={selectAll} /></th>
          {#each COLUMNS as c (c.key)}
            <th class:num={c.num} aria-sort={sortKey === c.key ? (sortDir === 1 ? 'ascending' : 'descending') : 'none'}>
              <button class="sort" onclick={() => sortBy(c.key)}>
                {c.label}<span class="arrow" aria-hidden="true">{sortKey === c.key ? (sortDir === 1 ? '▲' : '▼') : ''}</span>
              </button>
            </th>
          {/each}
        </tr>
      </thead>
      <tbody>
        {#each rows as a (a.id)}
          <tr class:selected={selected.has(a.id)} onclick={(e) => onRowClick(e, a.id)}>
            <td class="pick"><input type="checkbox" aria-label="Select {a.title}" checked={selected.has(a.id)} onchange={() => toggle(a.id)} /></td>
            <td class="wrap"><a href="/o/{offeringId}/assignments/{a.id}"><strong>{a.title}</strong></a><span class="sub mono">{a.slug}</span></td>
            <td>{a.settings.visibility === 'enrolled' ? 'enrolled only' : 'public'}</td>
            <td><span class="chip state {statusLabel(a)}">{statusLabel(a)}</span></td>
            <td>{a.settings.release_at ? fmtDateTime(a.settings.release_at) : '—'}</td>
            <td>{a.settings.due_at ? fmtDateTime(a.settings.due_at) : '—'}{#if a.settings.late_policy === 'reject'}<span class="sub">no late work</span>{/if}</td>
            <td>{a.settings.close_at ? fmtDateTime(a.settings.close_at) : '—'}</td>
            <td class="num">{a.latest_version ?? '—'}</td>
            <td class="num">{a.questions.length}</td>
            <td class="num">{trim(points(a))}</td>
            <td>{grading(a)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .pair {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0 16px;
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 0 0 8px;
    min-height: 30px;
  }
  table.assignments tbody tr {
    cursor: pointer;
  }
  table.assignments tbody tr:hover {
    background: var(--surface);
  }
  table.assignments tbody tr.selected {
    background: var(--accent-soft, rgba(46, 160, 110, 0.14));
  }
  th.pick,
  td.pick {
    width: 28px;
  }
  button.sort {
    font: inherit;
    font-weight: inherit;
    color: inherit;
    background: none;
    border: 0;
    padding: 0;
    cursor: pointer;
    white-space: nowrap;
  }
  th.num button.sort {
    width: 100%;
    text-align: right;
  }
  .arrow {
    display: inline-block;
    width: 1em;
    font-size: 0.7em;
    margin-left: 3px;
    color: var(--accent);
  }
  .chip.state.upcoming {
    color: var(--muted);
  }
  .chip.state.closed {
    color: var(--muted);
  }
</style>
