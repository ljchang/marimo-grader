<script lang="ts">
  import { onMount } from 'svelte';
  import { api, errorMessage, type Assignment, type Progress, type ProgressState } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import { blankSettings, fromForm } from '$lib/assignmentSettings';
  import {
    copyStudentLink,
    exportCanvas,
    gradeHref,
    phase,
    previewAsStudent,
    summary,
    tags,
    uploadLabel,
    when,
    type Phase,
  } from '$lib/assignmentView';
  import { router, type Params } from '$lib/router.svelte';
  import Drawer from '$lib/components/Drawer.svelte';
  import Loading from '$lib/components/Loading.svelte';
  import MoreMenu from '$lib/components/MoreMenu.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import SettingsFields from '$lib/components/SettingsFields.svelte';
  import SettingsPanel from '$lib/components/SettingsPanel.svelte';
  import UploadNotebookPanel from '$lib/components/UploadNotebookPanel.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  let assignments = $state<Assignment[] | null>(null);
  let progress = $state<Progress | null>(null);
  let error = $state<string | null>(null);
  let message = $state<string | null>(null);

  async function load() {
    try {
      const [list, p] = await Promise.all([
        api.offerings.assignments(offeringId),
        // The table still works without the counts; it just shows dashes.
        api.grading.progress(offeringId).catch(() => null),
      ]);
      assignments = list;
      progress = p;
    } catch (err) {
      error = errorMessage(err);
      assignments = [];
    }
  }
  onMount(load);

  // --- filtering, grouping, sorting ----------------------------------------

  type Filter = 'all' | 'grading' | Phase;
  let filter = $state<Filter>('all');
  let search = $state('');

  const prog = (a: Assignment) => progress?.assignments[a.id];
  const toGrade = (a: Assignment) => prog(a)?.to_grade ?? 0;

  function passes(a: Assignment, f: Filter): boolean {
    if (f === 'all') return true;
    if (f === 'grading') return toGrade(a) > 0;
    return phase(a) === f;
  }

  const counts = $derived.by(() => {
    const list = assignments ?? [];
    const c: Record<Filter, number> = { all: list.length, grading: 0, open: 0, upcoming: 0, closed: 0 };
    for (const a of list) {
      c[phase(a)] += 1;
      if (toGrade(a) > 0) c.grading += 1;
    }
    return c;
  });

  const FILTERS: { key: Filter; label: string }[] = [
    { key: 'all', label: 'All' },
    { key: 'grading', label: 'Needs grading' },
    { key: 'open', label: 'Open' },
    { key: 'upcoming', label: 'Coming up' },
    { key: 'closed', label: 'Closed' },
  ];

  type Key = 'title' | 'when' | 'progress' | 'average';
  let sortKey = $state<Key>('when');
  let sortDir = $state<1 | -1>(1);
  const COLUMNS: { key: Key; label: string; num?: boolean }[] = [
    { key: 'title', label: 'Assignment' },
    { key: 'when', label: 'When' },
    { key: 'progress', label: 'Class progress' },
    { key: 'average', label: 'Average', num: true },
  ];

  function value(a: Assignment, key: Key): string | number | null {
    switch (key) {
      case 'title':
        return a.title.toLowerCase();
      case 'when':
        return when(a).sortAt;
      case 'progress':
        return prog(a)?.submitted ?? null;
      case 'average':
        return prog(a)?.average ?? null;
    }
  }

  function sortBy(key: Key) {
    if (key === sortKey) sortDir = sortDir === 1 ? -1 : 1;
    else {
      sortKey = key;
      sortDir = 1;
    }
  }

  const visible = $derived.by(() => {
    const q = search.trim().toLowerCase();
    return (assignments ?? [])
      .filter((a) => passes(a, filter))
      .filter((a) => !q || a.title.toLowerCase().includes(q) || a.slug.includes(q))
      .sort((x, y) => {
        const a = value(x, sortKey);
        const b = value(y, sortKey);
        // Blanks (no date, no average) sort last whichever way the column runs.
        if (a === null || b === null) return a === b ? 0 : a === null ? 1 : -1;
        return (a < b ? -1 : a > b ? 1 : 0) * sortDir;
      });
  });

  const GROUPS: { key: Phase; label: string }[] = [
    { key: 'open', label: 'Open now' },
    { key: 'upcoming', label: 'Coming up' },
    { key: 'closed', label: 'Closed' },
  ];
  let closedOpen = $state(false);
  const groups = $derived(
    GROUPS.map((g) => ({ ...g, rows: visible.filter((a) => phase(a) === g.key) })).filter((g) => g.rows.length > 0),
  );
  // Closed work starts folded away, unless it is what was asked for.
  const expanded = (g: Phase) => g !== 'closed' || closedOpen || filter === 'closed' || search.trim() !== '';
  const order = $derived(groups.flatMap((g) => (expanded(g.key) ? g.rows : [])));

  // --- selection: click a row; shift-click selects a run ---------------------

  let selected = $state<Set<string>>(new Set());
  let anchor = $state<string | null>(null);

  function toggle(id: string, range = false) {
    const next = new Set(selected);
    if (range && anchor) {
      const ids = order.map((a) => a.id);
      const from = ids.indexOf(anchor);
      const to = ids.indexOf(id);
      const [i, j] = [Math.min(from, to), Math.max(from, to)];
      if (i >= 0) {
        for (const x of ids.slice(i, j + 1)) next.add(x);
        selected = next;
        return;
      }
    }
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected = next;
    anchor = id;
  }

  function onRowClick(e: MouseEvent, id: string) {
    // The title opens the assignment and the buttons do their own thing.
    if ((e.target as HTMLElement).closest('a, button, input, select, label')) return;
    toggle(id, e.shiftKey);
  }

  function onRowKey(e: KeyboardEvent, a: Assignment) {
    if (e.target !== e.currentTarget) return;
    if (e.key === ' ') {
      e.preventDefault();
      toggle(a.id, e.shiftKey);
    } else if (e.key === 'Enter') {
      router.navigate(`/o/${offeringId}/assignments/${a.id}`);
    }
  }

  const allSelected = $derived(order.length > 0 && order.every((a) => selected.has(a.id)));
  function selectAll() {
    selected = allSelected ? new Set() : new Set(order.map((a) => a.id));
  }
  function clearSelection() {
    selected = new Set();
    changingDue = false;
  }

  // --- change the due date of the selected assignments ---------------------

  let changingDue = $state(false);
  let newDue = $state('');
  let busy = $state(false);

  async function applyDue(e: SubmitEvent) {
    e.preventDefault();
    if (!newDue) return;
    busy = true;
    error = null;
    const due = new Date(newDue).toISOString();
    const picked = (assignments ?? []).filter((a) => selected.has(a.id));
    const failed: string[] = [];
    for (const a of picked) {
      try {
        await api.assignments.patch(offeringId, a.id, { settings: { due_at: due } });
      } catch (err) {
        failed.push(`${a.title}: ${errorMessage(err)}`);
      }
    }
    busy = false;
    const done = picked.length - failed.length;
    message = done > 0 ? `Due date changed on ${done} ${done === 1 ? 'assignment' : 'assignments'}.` : null;
    if (failed.length) error = `Not changed. ${failed.join(' ')}`;
    changingDue = false;
    newDue = '';
    await load();
  }

  // --- panels ----------------------------------------------------------------

  let settingsFor = $state<Assignment | null>(null);
  let uploadFor = $state<Assignment | null>(null);
  let creating = $state(false);

  function onSaved(a: Assignment) {
    settingsFor = null;
    message = `Saved the settings for ${a.title}.`;
    void load();
  }

  function menu(a: Assignment) {
    return [
      {
        label: 'Copy student link',
        onselect: () =>
          copyStudentLink(enrollment, a)
            .then(() => (message = `Copied the student link for ${a.title}.`))
            .catch((err) => (error = errorMessage(err))),
      },
      { label: 'Preview as a student', onselect: () => previewAsStudent(offeringId).catch((err) => (error = errorMessage(err))) },
      { label: uploadLabel(a), onselect: () => (uploadFor = a) },
      { label: 'Export to Canvas', onselect: () => exportCanvas(offeringId, [a.id]) },
    ];
  }

  let newSlug = $state('');
  let newTitle = $state('');
  let newSettings = $state(blankSettings());

  async function createAssignment(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = null;
    const slug = newSlug.trim();
    try {
      await api.assignments.create(offeringId, { slug, title: newTitle.trim(), settings: fromForm(newSettings) });
      message = `Created ${newTitle.trim()}. Upload its instructor notebook from More to give it questions.`;
      creating = false;
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

  const SEGMENTS: ProgressState[] = ['graded', 'waiting', 'failed', 'running', 'none'];
  const SEGMENT_WORDS: Record<ProgressState, string> = {
    graded: 'graded',
    waiting: 'waiting for you',
    failed: 'failed to run',
    running: 'being graded',
    none: 'not submitted',
  };
</script>

<div class="page-head">
  <div>
    <p class="eyebrow"><a href="/o/{offeringId}">{enrollment?.title ?? 'Course'}</a></p>
    <h1>Assignments</h1>
  </div>
  <div class="row">
    <button onclick={() => (creating = true)}>New assignment</button>
  </div>
</div>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}
{#if message}<Notice label="Done">{message}</Notice>{/if}

{#if assignments === null}
  <Loading />
{:else if assignments.length === 0}
  <p class="empty">No assignments yet. <code>grader publish</code> from the assignments repository creates one with its notebook and questions.</p>
{:else}
  <div class="filterbar">
    <div class="seg" role="radiogroup" aria-label="Show">
      {#each FILTERS as f (f.key)}
        <button role="radio" aria-checked={filter === f.key} class:on={filter === f.key} onclick={() => (filter = f.key)}>
          {f.label} <span class:hot={f.key === 'grading' && counts.grading > 0}>{counts[f.key]}</span>
        </button>
      {/each}
    </div>
    <div class="right">
      <button class="quiet" onclick={selectAll} disabled={order.length === 0}>{allSelected ? 'Clear selection' : 'Select all'}</button>
      <input class="search" type="search" placeholder="Search assignments" aria-label="Search assignments" bind:value={search} />
    </div>
  </div>

  {#if visible.length === 0}
    <p class="empty">Nothing matches. <button class="quiet" onclick={() => ((filter = 'all'), (search = ''))}>Show all assignments</button></p>
  {:else}
    <div class="tablewrap">
      <table class="data assignments">
        <thead>
          <tr>
            {#each COLUMNS as c (c.key)}
              <th class:num={c.num} aria-sort={sortKey === c.key ? (sortDir === 1 ? 'ascending' : 'descending') : 'none'}>
                <button class="sort" onclick={() => sortBy(c.key)}>
                  {c.label}<span class="arrow" aria-hidden="true">{sortKey === c.key ? (sortDir === 1 ? '▲' : '▼') : ''}</span>
                </button>
              </th>
            {/each}
            <th><span class="sr">Actions</span></th>
          </tr>
        </thead>
        {#each groups as g (g.key)}
          <tbody>
            <tr class="group">
              <th colspan="5" scope="rowgroup">
                {#if g.key === 'closed' && filter !== 'closed' && !search.trim()}
                  <button class="disclose" aria-expanded={closedOpen} onclick={() => (closedOpen = !closedOpen)}>
                    <span class="caret" class:turned={closedOpen} aria-hidden="true">▸</span>{g.label} <span class="n">{g.rows.length}</span>
                  </button>
                  {#if !closedOpen}
                    <span class="hint">{g.rows.slice(0, 2).map((a) => a.title).join(', ')}{g.rows.length > 2 ? `, and ${g.rows.length - 2} more` : ''}</span>
                  {/if}
                {:else}
                  {g.label} <span class="n">{g.rows.length}</span>
                {/if}
              </th>
            </tr>
            {#if expanded(g.key)}
              {#each g.rows as a (a.id)}
                {@const p = prog(a)}
                {@const w = when(a)}
                {@const roster = progress?.roster ?? 0}
                <tr
                  class="item"
                  class:selected={selected.has(a.id)}
                  tabindex="0"
                  aria-selected={selected.has(a.id)}
                  onclick={(e) => onRowClick(e, a.id)}
                  onmousedown={(e) => e.shiftKey && e.preventDefault()}
                  onkeydown={(e) => onRowKey(e, a)}
                >
                  <td class="wrap title">
                    <a href="/o/{offeringId}/assignments/{a.id}">{a.title}</a>
                    <span class="sub">{summary(a)}</span>
                    {#if tags(a).length}
                      <span class="tags">{#each tags(a) as t (t.label)}<span class="tag" class:warn={t.warn} title={t.title}>{t.label}</span>{/each}</span>
                    {/if}
                  </td>
                  <td class="wrap">
                    <span class="when" class:soon={w.soon}>{w.text}</span>
                    <span class="sub">{w.detail}</span>
                  </td>
                  <td class="wrap">
                    {#if !p || (g.key === 'upcoming' && p.submitted === 0)}
                      <span class="sub">{g.key === 'upcoming' ? 'Not open yet' : '—'}</span>
                    {:else}
                      <div
                        class="bar"
                        role="img"
                        aria-label={SEGMENTS.filter((s) => p.students[s] > 0).map((s) => `${p.students[s]} ${SEGMENT_WORDS[s]}`).join(', ')}
                        title={SEGMENTS.filter((s) => p.students[s] > 0).map((s) => `${p.students[s]} ${SEGMENT_WORDS[s]}`).join(', ')}
                      >
                        {#each SEGMENTS as s (s)}{#if p.students[s] > 0}<i class={s} style:flex-grow={p.students[s]}></i>{/if}{/each}
                      </div>
                      <span class="sub">
                        {p.submitted} of {roster} submitted{#if p.to_grade > 0}. <b class="w">{p.to_grade} to grade</b>{/if}{#if p.students.failed > 0}{p.to_grade > 0 ? ', ' : '. '}<b class="f">{p.students.failed} failed</b>{/if}
                      </span>
                    {/if}
                  </td>
                  <td class="num" title={p?.average != null ? `Average over the ${p.averaged_over} students whose work is fully graded` : ''}>
                    {p?.average != null ? `${Math.round(p.average)}%` : '—'}
                  </td>
                  <td class="acts">
                    {#if (p?.to_grade ?? 0) > 0}
                      <a class="btn primary" href={gradeHref(offeringId, a, p)}>Grade <span class="badge">{p?.to_grade}</span></a>
                    {:else if (p?.submitted ?? 0) > 0}
                      <a class="btn" href="/o/{offeringId}/assignments/{a.id}">Review</a>
                    {:else}
                      <button disabled title="Nothing submitted yet">Grade</button>
                    {/if}
                    <button onclick={() => (settingsFor = a)}>Settings</button>
                    <MoreMenu items={menu(a)} ariaLabel="More actions for {a.title}" />
                  </td>
                </tr>
              {/each}
            {/if}
          </tbody>
        {/each}
      </table>
    </div>
  {/if}
{/if}

{#if selected.size > 0}
  <div class="bulk" role="region" aria-label="Selected assignments">
    <span><b>{selected.size} selected</b> <span class="muted">Click a row to add or remove it</span></span>
    {#if changingDue}
      <form class="due" onsubmit={applyDue}>
        <label class="sr" for="bulk-due">New due date</label>
        <input id="bulk-due" type="datetime-local" required bind:value={newDue} />
        <button class="primary" type="submit" disabled={busy}>{busy ? 'Changing…' : 'Change'}</button>
        <button class="quiet" type="button" onclick={() => (changingDue = false)}>Cancel</button>
      </form>
    {:else}
      <button onclick={() => exportCanvas(offeringId, [...selected])}>Export to Canvas</button>
      <button onclick={() => (changingDue = true)}>Change due date</button>
      <button class="quiet" onclick={clearSelection}>Clear</button>
    {/if}
  </div>
{/if}

{#if settingsFor}
  <SettingsPanel {offeringId} assignment={settingsFor} onclose={() => (settingsFor = null)} onsaved={onSaved} />
{/if}

{#if uploadFor}
  <UploadNotebookPanel
    {offeringId}
    assignment={uploadFor}
    onclose={() => (uploadFor = null)}
    onpublished={(m) => {
      uploadFor = null;
      message = m;
      void load();
    }}
  />
{/if}

{#if creating}
  <Drawer title="New assignment" subtitle="Give it questions afterwards by uploading its instructor notebook." onclose={() => (creating = false)}>
    <form id="new-assignment" onsubmit={createAssignment}>
      <label class="line"><span>Title</span><input required bind:value={newTitle} placeholder="General linear model" /></label>
      <label class="line"><span>Short name<small>Lowercase, used in links</small></span><input required bind:value={newSlug} placeholder="glm" pattern="[a-z0-9-]+" /></label>
      <SettingsFields bind:form={newSettings} />
    </form>
    {#snippet footer()}
      <button class="primary" type="submit" form="new-assignment" disabled={busy}>Create assignment</button>
      <button class="quiet" onclick={() => (creating = false)}>Cancel</button>
    {/snippet}
  </Drawer>
{/if}

<style>
  .filterbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 12px;
  }
  .seg {
    display: inline-flex;
    flex-wrap: wrap;
    border: 1px solid var(--rule);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .seg button {
    border: 0;
    border-radius: 0;
    background: none;
    color: var(--muted);
    padding: 7px 12px;
  }
  .seg button + button {
    border-left: 1px solid var(--rule);
  }
  .seg button.on {
    background: var(--surface);
    color: var(--ink);
    font-weight: 600;
  }
  .seg span {
    font-weight: 400;
    color: var(--muted);
  }
  .seg span.hot {
    color: var(--warn);
    font-weight: 700;
  }
  .right {
    display: flex;
    gap: 8px;
    align-items: center;
  }
  .search {
    width: 240px;
  }
  /* Floats over the bottom of the window so selecting never moves the rows. */
  .bulk {
    position: fixed;
    left: 50%;
    bottom: 20px;
    z-index: 20;
    transform: translateX(-50%);
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 8px;
    max-width: calc(100vw - 32px);
    padding: 10px 14px;
    background: var(--surface);
    border: 1px solid var(--accent);
    border-radius: 8px;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
    font-size: 14px;
  }
  .bulk > span {
    margin-right: 6px;
  }
  .bulk button {
    padding: 6px 10px;
    font-size: 13px;
  }
  .due {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .due input {
    width: auto;
    padding: 4px 8px;
    font-size: 14px;
  }
  .sr {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip: rect(0 0 0 0);
    white-space: nowrap;
  }
  table.assignments td {
    vertical-align: middle;
  }
  button.sort {
    font: inherit;
    font-weight: inherit;
    color: inherit;
    background: none;
    border: 0;
    padding: 0;
    white-space: nowrap;
  }
  th.num button.sort {
    width: 100%;
    justify-content: flex-end;
  }
  .arrow {
    display: inline-block;
    width: 1em;
    font-size: 0.7em;
    margin-left: 3px;
    color: var(--accent);
  }
  tr.group th {
    position: static;
    font-size: 15px;
    color: var(--ink);
    padding: 22px 12px 6px;
    border-bottom: 1px solid var(--rule);
  }
  tr.group:hover {
    background: none;
  }
  tr.group .n {
    color: var(--muted);
    font-weight: 400;
    margin-left: 4px;
  }
  .disclose {
    border: 0;
    padding: 0;
    background: none;
    font-weight: 600;
    font-size: 15px;
  }
  .disclose:hover {
    background: none;
  }
  .caret {
    display: inline-block;
    width: 14px;
    transition: transform 120ms;
  }
  .caret.turned {
    transform: rotate(90deg);
  }
  .hint {
    font-weight: 400;
    font-size: 13px;
    color: var(--muted);
    margin-left: 12px;
  }
  tr.item {
    cursor: pointer;
  }
  tr.item:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: -2px;
  }
  tr.item.selected,
  tr.item.selected:hover {
    background: var(--accent-soft);
  }
  tr.item.selected td:first-child {
    box-shadow: inset 3px 0 0 var(--accent);
  }
  td.title a {
    font-weight: 600;
    color: var(--ink);
  }
  td.title a:hover {
    color: var(--accent);
  }
  .tags {
    display: flex;
    gap: 6px;
    margin-top: 5px;
  }
  .tag {
    font-size: 12px;
    padding: 0 7px;
    border-radius: 9px;
    border: 1px solid var(--rule);
    color: var(--muted);
    white-space: nowrap;
  }
  .tag.warn {
    border-color: var(--warn);
    color: var(--warn);
  }
  .when {
    font-weight: 600;
  }
  .when.soon {
    color: var(--warn);
  }
  .bar {
    display: flex;
    gap: 1px;
    width: 220px;
    max-width: 100%;
    height: 8px;
    margin: 4px 0 5px;
    border-radius: 4px;
    overflow: hidden;
  }
  .bar i {
    display: block;
    flex-basis: 0;
    background: var(--rule);
  }
  .bar i.graded {
    background: var(--accent);
  }
  .bar i.waiting {
    background: var(--warn);
  }
  .bar i.failed {
    background: var(--danger);
  }
  .bar i.running {
    background: var(--muted);
  }
  b.w {
    color: var(--warn);
    font-weight: 600;
  }
  b.f {
    color: var(--danger);
    font-weight: 600;
  }
  td.acts {
    text-align: right;
  }
  td.acts :global(button),
  td.acts .btn {
    padding: 6px 10px;
    font-size: 13px;
    margin-left: 4px;
  }
  .badge {
    display: inline-block;
    min-width: 18px;
    padding: 1px 6px;
    border-radius: 9px;
    background: var(--warn);
    color: #1d1606;
    font-size: 12px;
    font-weight: 700;
    text-align: center;
  }
  .line {
    display: grid;
    grid-template-columns: 140px minmax(0, 1fr);
    gap: 10px;
    align-items: center;
    margin: 16px 0 0;
    font-size: 14px;
  }
  .line small {
    display: block;
    font-size: 12px;
    color: var(--muted);
  }
  @media (max-width: 720px) {
    .search {
      width: 100%;
    }
    .right {
      width: 100%;
    }
  }
</style>
