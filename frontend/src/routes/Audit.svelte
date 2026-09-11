<script lang="ts">
  // Audit log. Used two ways: /o/:offering/audit (instructor: everything in the offering,
  // including grade changes) and inside /admin (platform events only, no grades).
  import { onMount } from 'svelte';
  import { api, errorMessage, type AuditEntry } from '../lib/api';
  import { fmtDateTime } from '../lib/format';
  import Loading from '../lib/components/Loading.svelte';
  import Notice from '../lib/components/Notice.svelte';

  type Params = { offering?: string };
  let { params = {}, scope = 'offering' }: { params?: Params; scope?: 'offering' | 'platform' } = $props();
  const offeringId = $derived(params.offering ?? '');

  let entries = $state<AuditEntry[] | null>(null);
  let error = $state<string | null>(null);
  let filter = $state('');

  const visible = $derived(
    (entries ?? []).filter((e) => {
      if (!filter) return true;
      const hay = `${e.actor ?? ''} ${e.entity} ${e.action} ${e.entity_id} ${e.reason ?? ''} ${e.offering ?? ''}`.toLowerCase();
      return hay.includes(filter.toLowerCase());
    }),
  );

  async function load() {
    error = null;
    try {
      entries = scope === 'platform' ? await api.admin.audit() : await api.grading.audit(offeringId);
    } catch (err) {
      error = errorMessage(err);
    }
  }
  onMount(load);

  function summary(e: AuditEntry): string {
    const a = e.after ?? {};
    const b = e.before ?? {};
    if (e.entity === 'score') return `${b.total ?? '—'} → ${a.total ?? '—'}${a.final ? ' (final)' : ''}`;
    if (e.entity === 'roster') return `+${a.added ?? 0} −${a.dropped ?? 0} moved ${a.moved ?? 0}`;
    if (e.entity === 'assignment_version') return `v${a.version ?? '?'} · ${(a.questions ?? []).length} questions`;
    if (e.entity === 'enrollment') return `${a.netid ?? ''} ${a.role ?? ''}`.trim();
    if (e.entity === 'assignment') return a.slug ?? a.title ?? '';
    if (e.entity === 'course' || e.entity === 'offering') return a.slug ?? a.term ?? a.title ?? '';
    if (e.entity === 'export') return (a.assignments ?? []).length + ' assignment(s)';
    if (e.entity === 'user') return `platform_admin=${a.platform_admin}`;
    return '';
  }
</script>

<div class="audit">
  {#if scope === 'offering'}
    <div class="page-head">
      <div><h1>Change log</h1><p class="eyebrow">Grade changes, roster imports, settings, publishes, and exports for this course.</p></div>
    </div>
  {/if}

  {#if error}<Notice kind="error" label="Error">{error}</Notice>{/if}

  <div class="tools">
    <input id="audit-filter" type="search" placeholder="Filter by NetID, entity, action, reason" bind:value={filter} />
    <span class="muted small">{visible.length} of {entries?.length ?? 0}</span>
    <button type="button" class="quiet small" onclick={load}>Refresh</button>
  </div>

  {#if entries === null}
    <Loading label="Loading audit log" />
  {:else if visible.length === 0}
    <p class="muted">No entries.</p>
  {:else}
    <div class="tablewrap">
      <table>
        <thead>
          <tr>
            <th>When</th><th>Who</th>{#if scope === 'platform'}<th>Offering</th>{/if}<th>Entity</th><th>Action</th><th>Change</th><th>Reason</th>
          </tr>
        </thead>
        <tbody>
          {#each visible as e (e.id)}
            <tr>
              <td class="nowrap">{fmtDateTime(e.at)}</td>
              <td class="mono">{e.actor ?? '—'}</td>
              {#if scope === 'platform'}<td class="mono">{e.offering ?? '—'}</td>{/if}
              <td>{e.entity}</td>
              <td>{e.action}</td>
              <td class="mono small">{summary(e)}</td>
              <td class="muted">{e.reason ?? ''}</td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>

<style>
  .tools { display: flex; gap: 0.75rem; align-items: center; margin: 0.75rem 0; flex-wrap: wrap; }
  .tools input { flex: 1; min-width: 220px; font: inherit; padding: 0.4rem 0.6rem; border: 1px solid var(--rule); border-radius: 4px; background: var(--paper); color: var(--ink); }
  .tablewrap { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 0.9rem; font-variant-numeric: tabular-nums; }
  th, td { text-align: left; padding: 0.4rem 0.6rem; border-bottom: 1px solid var(--rule); vertical-align: top; }
  th { font-size: 13px; color: var(--muted); }
  .nowrap { white-space: nowrap; }
  .mono { font-family: var(--mono, ui-monospace, monospace); font-size: 0.85rem; }
</style>
