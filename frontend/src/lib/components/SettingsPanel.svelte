<script lang="ts">
  // One assignment's settings in a side panel: the same panel opens from a row
  // of the assignments table and from the assignment page.
  import { api, errorMessage, type Assignment } from '$lib/api';
  import { fromForm, toForm } from '$lib/assignmentSettings';
  import Drawer from './Drawer.svelte';
  import Notice from './Notice.svelte';
  import SettingsFields from './SettingsFields.svelte';

  let {
    offeringId,
    assignment,
    onclose,
    onsaved,
  }: {
    offeringId: string;
    assignment: Assignment;
    onclose: () => void;
    onsaved: (a: Assignment) => void;
  } = $props();

  // The form is a copy taken when the panel opens; nothing changes until Save.
  // svelte-ignore state_referenced_locally
  let title = $state(assignment.title);
  // svelte-ignore state_referenced_locally
  let form = $state(toForm(assignment.settings));
  let busy = $state(false);
  let error = $state<string | null>(null);

  async function save(e: SubmitEvent) {
    e.preventDefault();
    busy = true;
    error = null;
    try {
      const a = await api.assignments.patch(offeringId, assignment.id, { title: title.trim(), settings: fromForm(form) });
      onsaved(a);
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }
</script>

<Drawer title="{assignment.title} settings" subtitle="Changes apply when you save." {onclose}>
  <form id="settings-form" onsubmit={save}>
    {#if error}<Notice kind="error" label="Not saved">{error}</Notice>{/if}
    <label class="line"><span>Title</span><input required bind:value={title} /></label>
    <SettingsFields bind:form />
  </form>
  {#snippet footer()}
    <button class="primary" type="submit" form="settings-form" disabled={busy}>{busy ? 'Saving…' : 'Save settings'}</button>
    <button class="quiet" type="button" onclick={onclose}>Cancel</button>
  {/snippet}
</Drawer>

<style>
  .line {
    display: grid;
    grid-template-columns: 140px minmax(0, 1fr);
    gap: 10px;
    align-items: center;
    margin: 16px 0 0;
    font-size: 14px;
  }
</style>
