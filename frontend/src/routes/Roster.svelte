<script lang="ts">
  import { onMount } from 'svelte';
  import {
    api,
    errorMessage,
    type RosterApplied,
    type RosterEnrollment,
    type RosterPreview,
    type RosterRow,
    type RosterSource,
  } from '$lib/api';
  import { auth } from '$lib/auth.svelte';
  import type { Params } from '$lib/router.svelte';
  import Notice from '$lib/components/Notice.svelte';
  import Loading from '$lib/components/Loading.svelte';

  let { params }: { params: Params } = $props();
  const offeringId = $derived(params.offering ?? '');
  const enrollment = $derived(auth.enrollment(offeringId));

  let roster = $state<RosterEnrollment[] | null>(null);
  let error = $state<string | null>(null);

  let files = $state<FileList | null>(null);
  let source = $state<RosterSource>('canvas_csv');
  let preview = $state<RosterPreview | null>(null);
  let excluded = $state<Set<string>>(new Set());
  let busy = $state(false);
  let applied = $state<RosterApplied | null>(null);

  // Teaching staff (TAs and co-instructors) are added by NetID; they sign in with SSO like everyone else.
  let staffNetid = $state('');
  let staffRole = $state<'ta' | 'instructor'>('ta');
  let staffSections = $state('');
  let staffName = $state('');
  let staffMessage = $state<string | null>(null);

  async function addStaff(e: SubmitEvent) {
    e.preventDefault();
    staffMessage = null;
    error = null;
    try {
      const sections = staffSections.split(',').map((x) => x.trim()).filter(Boolean);
      const r = await api.roster.addStaff(offeringId, {
        netid: staffNetid.trim().toLowerCase(),
        role: staffRole,
        ta_sections: sections,
        display_name: staffName.trim() || undefined,
      });
      staffMessage = `${r.netid} added as ${r.role}${sections.length ? ` for sections ${sections.join(', ')}` : ''}.`;
      staffNetid = ''; staffSections = ''; staffName = '';
      await loadRoster();
    } catch (err) {
      error = errorMessage(err);
    }
  }

  // One student at a time: the late add, and the person Canvas has not caught up with.
  let studentNetid = $state('');
  let studentName = $state('');
  let studentSection = $state('');
  let studentMessage = $state<string | null>(null);
  let dropping = $state<string | null>(null);

  async function addStudent(e: SubmitEvent) {
    e.preventDefault();
    studentMessage = null;
    error = null;
    try {
      const r = await api.roster.addStudent(offeringId, {
        netid: studentNetid.trim().toLowerCase(),
        display_name: studentName.trim() || undefined,
        section: studentSection.trim() || undefined,
      });
      studentMessage = `${r.netid} added.`;
      studentNetid = ''; studentName = ''; studentSection = '';
      await loadRoster();
    } catch (err) {
      error = errorMessage(err);
    }
  }

  async function drop(netid: string, role: string) {
    const what = role === 'student' ? 'student' : role === 'ta' ? 'teaching assistant' : 'instructor';
    if (!confirm(`Remove ${netid} (${what}) from this offering?\n\nTheir submissions and grades are kept, and re-adding them or a later import restores the same record.`)) return;
    error = null;
    dropping = netid;
    try {
      await api.roster.drop(offeringId, netid);
      await loadRoster();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      dropping = null;
    }
  }

  type Bucket = keyof RosterPreview;
  const buckets: { key: Bucket; label: string; hint: string }[] = [
    { key: 'adds', label: 'Adds', hint: 'in the file, not yet enrolled' },
    { key: 'moves', label: 'Section moves', hint: 'enrolled, section differs' },
    { key: 'drops', label: 'Drops', hint: 'enrolled, missing from the file' },
    { key: 'unmatched', label: 'Unmatched', hint: 'no NetID could be resolved; never applied' },
  ];

  function rowKey(bucket: Bucket, row: RosterRow): string {
    return `${bucket}:${row.netid}`;
  }

  function toggle(bucket: Bucket, row: RosterRow) {
    const k = rowKey(bucket, row);
    const next = new Set(excluded);
    if (next.has(k)) next.delete(k);
    else next.add(k);
    excluded = next;
  }

  const payload = $derived.by((): RosterPreview | null => {
    if (!preview) return null;
    const keep = <T extends RosterRow>(bucket: Bucket, rows: T[]) =>
      rows.filter((r) => !excluded.has(rowKey(bucket, r)));
    return {
      adds: keep('adds', preview.adds),
      drops: keep('drops', preview.drops),
      moves: keep('moves', preview.moves),
      unmatched: [],
    };
  });

  // A drop is soft: the enrollment row survives because submissions and grades
  // reference it. That is a storage concern, not something to show the class.
  const enrolled = $derived(roster?.filter((r) => r.status === 'active') ?? null);

  async function loadRoster() {
    try {
      roster = await api.roster.list(offeringId);
    } catch (err) {
      error = errorMessage(err);
      roster = [];
    }
  }
  onMount(loadRoster);

  async function runPreview(e: SubmitEvent) {
    e.preventDefault();
    const file = files?.[0];
    if (!file) return;
    busy = true;
    error = null;
    applied = null;
    try {
      preview = await api.roster.preview(offeringId, file, source);
      excluded = new Set();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  async function apply() {
    if (!payload) return;
    busy = true;
    error = null;
    try {
      applied = await api.roster.apply(offeringId, payload);
      preview = null;
      files = null;
      await loadRoster();
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }

  const changeCount = $derived(
    payload ? payload.adds.length + payload.drops.length + payload.moves.length : 0,
  );
</script>

<div class="page-head">
  <div>
    <p class="eyebrow"><a href="/o/{offeringId}">{enrollment?.title ?? 'Course'}</a></p>
    <h1>Roster</h1>
  </div>
  <div class="meta"><span>{roster?.length ?? 0} enrolled, including staff</span></div>
</div>

{#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}
{#if applied}
  <Notice label="Applied">
    {applied.added} added, {applied.moved} moved, {applied.dropped} dropped.
  </Notice>
{/if}

<section class="block">
  <div class="block-head"><h2>Import students</h2><span class="muted small">Upload a Canvas gradebook export or a Banner class list. You review the changes before anything is applied.</span></div>
  <form class="card import" onsubmit={runPreview}>
    <div class="row">
      <label class="field" style="margin:0;flex:1;min-width:220px">
        <span>File</span>
        <input type="file" accept=".csv,.txt,.xlsx,.xls" bind:files required />
      </label>
      <fieldset class="src">
        <legend class="muted small">Source</legend>
        <label><input type="radio" value="canvas_csv" bind:group={source} />Canvas CSV</label>
        <label><input type="radio" value="banner" bind:group={source} />Banner</label>
      </fieldset>
      <button class="primary" type="submit" disabled={busy || !files?.length}>{busy ? 'Working' : 'Preview changes'}</button>
    </div>
  </form>
</section>

{#if preview && payload}
  <section class="block">
    <div class="block-head">
      <h2>Preview <span class="count" class:hot={changeCount > 0}>{changeCount}</span></h2>
      <span class="muted small">Untick a row to leave it out. Dropped students keep their submissions and grades.</span>
    </div>

    <div class="grid-2">
      {#each buckets as b (b.key)}
        {@const rows = preview[b.key]}
        <div>
          <h3>{b.label} <span class="count">{rows.length}</span> <span class="muted small" style="font-weight:400">{b.hint}</span></h3>
          {#if rows.length === 0}
            <p class="empty">None.</p>
          {:else}
            <div class="tablewrap">
              <table class="data">
                <thead>
                  <tr>
                    {#if b.key !== 'unmatched'}<th></th>{/if}
                    <th>NetID</th><th>Name</th><th>Section</th>
                  </tr>
                </thead>
                <tbody>
                  {#each rows as r (r.netid + (r.section ?? ''))}
                    <tr class:excluded={excluded.has(rowKey(b.key, r))}>
                      {#if b.key !== 'unmatched'}
                        <td><input type="checkbox" checked={!excluded.has(rowKey(b.key, r))} onchange={() => toggle(b.key, r)} aria-label="Include {r.netid}" /></td>
                      {/if}
                      <td class="mono">{r.netid || '—'}</td>
                      <td class="wrap">{r.display_name}</td>
                      <td>
                        {#if b.key === 'moves' && 'from_section' in r && r.from_section}
                          <span class="muted">{r.from_section} →</span>
                        {/if}
                        {r.section ?? '—'}
                      </td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        </div>
      {/each}
    </div>

    <div class="actions">
      <button class="primary" onclick={apply} disabled={busy || changeCount === 0}>Apply {changeCount} change{changeCount === 1 ? '' : 's'}</button>
      <button onclick={() => (preview = null)} disabled={busy}>Discard</button>
    </div>
  </section>
{/if}

<section class="block">
  <div class="block-head"><h2>Teaching staff</h2><span class="muted small">Add a TA or co-instructor by NetID. They sign in with Dartmouth like everyone else.</span></div>
  <form class="card import" onsubmit={addStaff}>
    <div class="row">
      <label class="field" style="margin:0;min-width:160px"><span>NetID</span><input id="staff-netid" type="text" bind:value={staffNetid} required placeholder="f00abc1" /></label>
      <label class="field" style="margin:0"><span>Role</span>
        <select id="staff-role" bind:value={staffRole}><option value="ta">TA</option><option value="instructor">Instructor</option></select>
      </label>
      <label class="field" style="margin:0;min-width:200px"><span>Sections a TA may grade (comma-separated, blank for all)</span><input id="staff-sections" type="text" bind:value={staffSections} placeholder="01, 02" disabled={staffRole !== 'ta'} /></label>
      <label class="field" style="margin:0;min-width:160px"><span>Display name (optional)</span><input id="staff-name" type="text" bind:value={staffName} /></label>
      <button class="primary" type="submit" disabled={!staffNetid.trim()}>Add</button>
    </div>
    {#if staffMessage}<p class="small muted" style="margin:0.5rem 0 0">{staffMessage}</p>{/if}
  </form>
</section>

<section class="block">
  <div class="block-head">
    <h2>Add a student</h2>
    <p class="small muted" style="margin:0">For a late add. Importing the Canvas roster again is the better way to make bulk changes.</p>
  </div>
  <form class="card import" onsubmit={addStudent}>
    <div class="row">
      <label class="field" style="margin:0;min-width:160px"><span>NetID</span><input type="text" bind:value={studentNetid} required placeholder="f00abc1" /></label>
      <label class="field" style="margin:0;min-width:200px"><span>Name (optional)</span><input type="text" bind:value={studentName} placeholder="Taken from Dartmouth at first sign-in" /></label>
      <label class="field" style="margin:0;min-width:120px"><span>Section (optional)</span><input type="text" bind:value={studentSection} placeholder="01" /></label>
      <button class="primary" type="submit" disabled={studentNetid.trim() === ''}>Add</button>
    </div>
    {#if studentMessage}<p class="small muted" style="margin:0.5rem 0 0">{studentMessage}</p>{/if}
  </form>
</section>

<section class="block">
  <div class="block-head"><h2>Current roster <span class="count">{enrolled?.length ?? 0}</span></h2></div>
  {#if enrolled === null}
    <Loading />
  {:else if enrolled.length === 0}
    <p class="empty">Nobody is enrolled yet. Import the Canvas roster above.</p>
  {:else}
    <div class="tablewrap">
      <table class="data">
        <thead><tr><th>NetID</th><th>Name</th><th>Section</th><th>Role</th><th></th></tr></thead>
        <tbody>
          {#each enrolled as r (r.netid)}
            <tr>
              <td class="mono">{r.netid}</td>
              <td class="wrap">{r.display_name}</td>
              <td>{r.section ?? '—'}</td>
              <td>{r.role === 'ta' ? 'Teaching assistant' : r.role === 'instructor' ? 'Instructor' : 'Student'}</td>
              <td class="rowacts">
                {#if r.role === 'student'}<a href="/o/{offeringId}/students/{r.netid}">Submissions</a>{/if}
                <button class="linkish" onclick={() => drop(r.netid, r.role)} disabled={dropping === r.netid}>
                  {dropping === r.netid ? 'Removing…' : 'Remove'}
                </button>
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</section>

<p class="muted" id="roster-audit" style="margin-top:8px">Every grade, roster, and settings change is recorded. <a href="/o/{offeringId}/audit">Open the change log</a> if you ever need to trace one.</p>

<style>
  .rowacts {
    display: flex;
    gap: 12px;
    align-items: center;
    justify-content: flex-end;
  }
  .linkish {
    background: none;
    border: 0;
    padding: 0;
    font: inherit;
    color: var(--red, #8a2a00);
    cursor: pointer;
  }
  .linkish:disabled {
    opacity: 0.5;
    cursor: default;
  }
  .import .row {
    align-items: flex-end;
  }
  fieldset.src {
    border: 0;
    padding: 0;
    margin: 0;
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
  }
  fieldset.src legend {
    padding: 0;
    margin-bottom: 6px;
  }
  fieldset.src label {
    white-space: nowrap;
    font-size: 13px;
  }
  tr.excluded td {
    color: var(--muted);
    text-decoration: line-through;
  }
</style>
