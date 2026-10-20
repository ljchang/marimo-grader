<script lang="ts">
  import type { Environment } from '$lib/api';
  import { ENVIRONMENTS, POLICIES, type SettingsForm } from '$lib/assignmentSettings';
  import { fmtPolicy } from '$lib/format';

  let { form = $bindable() }: { form: SettingsForm } = $props();

  function toggleEnv(env: Environment) {
    form.environments = form.environments.includes(env)
      ? form.environments.filter((e) => e !== env)
      : [...form.environments, env];
  }
</script>

<div class="settings-grid">
  <label class="field">
    <span>Who can open it</span>
    <select bind:value={form.visibility}>
      <option value="public">Anyone (course book)</option>
      <option value="enrolled">Enrolled students only (exam)</option>
    </select>
  </label>
  <label class="field"><span>Opens <span class="muted">(notebook + data{form.visibility === 'enrolled' ? '; blank = hidden from students' : ''})</span></span><input type="datetime-local" bind:value={form.release_at} /></label>
  <label class="field"><span>Due</span><input type="datetime-local" bind:value={form.due_at} /></label>
  <label class="field"><span>Closes <span class="muted">(data + submissions{form.visibility === 'enrolled' ? '; blank = at the deadline' : ''})</span></span><input type="datetime-local" bind:value={form.close_at} /></label>
  <label class="field">
    <span>After the deadline</span>
    <select bind:value={form.late_policy}>
      <option value="accept">Accept, marked late</option>
      <option value="reject">Refuse submissions</option>
    </select>
  </label>
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
        <label class="small"><input type="checkbox" checked={form.environments.includes(env)} onchange={() => toggleEnv(env)} />{env}</label>
      {/each}
    </div>
  </div>
  <label class="field inline"><input type="checkbox" bind:checked={form.log_checks} /><span>Log check events</span></label>
  <label class="field inline"><input type="checkbox" bind:checked={form.autograde} /><span>Autograde submissions</span></label>
  <label class="field inline" title="Off for notebooks too heavy for the grader: you read the code and the files saved under storage.private()/<slug>/"><input type="checkbox" bind:checked={form.render} /><span>Re-run to render submissions</span></label>
  <label class="field inline"><input type="checkbox" bind:checked={form.notebook_submission} /><span>Whole-notebook submission</span></label>
  {#if form.notebook_submission}
    <label class="field"><span>Notebook points <span class="muted">(0 = receipt only)</span></span><input type="number" min="0" step="1" bind:value={form.notebook_points} /></label>
  {/if}
</div>

<style>
  .settings-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 0 16px;
  }
</style>
