<script lang="ts">
  import type { Environment } from '$lib/api';
  import { ENVIRONMENTS, POLICIES, type SettingsForm } from '$lib/assignmentSettings';
  import { fmtPolicy } from '$lib/format';

  let { form = $bindable() }: { form: SettingsForm } = $props();

  const exam = $derived(form.visibility === 'enrolled');
  const policyLabel = (p: (typeof POLICIES)[number]) => {
    const s = fmtPolicy(p);
    return s.charAt(0).toUpperCase() + s.slice(1);
  };

  function toggleEnv(env: Environment) {
    form.environments = form.environments.includes(env)
      ? form.environments.filter((e) => e !== env)
      : [...form.environments, env];
  }
</script>

<fieldset>
  <legend>When</legend>
  <label class="line">
    <span>Opens<small>{exam ? 'Blank keeps it hidden from students' : 'Blank opens it now'}</small></span>
    <input type="datetime-local" bind:value={form.release_at} />
  </label>
  <label class="line"><span>Due</span><input type="datetime-local" bind:value={form.due_at} /></label>
  <label class="line">
    <span>Closes<small>{exam ? 'Blank closes it at the due time' : 'Blank keeps it open'}</small></span>
    <input type="datetime-local" bind:value={form.close_at} />
  </label>
  <label class="line">
    <span>After the due time</span>
    <select bind:value={form.late_policy}>
      <option value="accept">Accept, marked late</option>
      <option value="reject">Refuse submissions</option>
    </select>
  </label>
</fieldset>

<fieldset>
  <legend>Who and where</legend>
  <label class="line">
    <span>Who can open it</span>
    <select bind:value={form.visibility}>
      <option value="public">Anyone with the course book</option>
      <option value="enrolled">Enrolled students only</option>
    </select>
  </label>
  <div class="line">
    <span>Works in</span>
    <div class="envs">
      {#each ENVIRONMENTS as env (env)}
        <label><input type="checkbox" checked={form.environments.includes(env)} onchange={() => toggleEnv(env)} />{env}</label>
      {/each}
    </div>
  </div>
</fieldset>

<fieldset>
  <legend>Attempts and grading</legend>
  <label class="line">
    <span>Attempts</span>
    <input type="number" min="1" step="1" placeholder="Unlimited" bind:value={form.attempts_allowed} />
  </label>
  <label class="line">
    <span>Which attempt counts</span>
    <select bind:value={form.grade_policy}>
      {#each POLICIES as p (p)}<option value={p}>{policyLabel(p)}</option>{/each}
    </select>
  </label>
  <label class="check">
    <input type="checkbox" bind:checked={form.autograde} />
    <span>Grade checks automatically<small>Off: you grade every answer by hand</small></span>
  </label>
  <label class="check">
    <input type="checkbox" bind:checked={form.render} />
    <span>Re-run each submission<small>Off for notebooks too heavy for the grader; you read the code and the files saved under <code>storage.private()</code></small></span>
  </label>
  <label class="check">
    <input type="checkbox" bind:checked={form.notebook_submission} />
    <span>Students submit the whole notebook</span>
  </label>
  {#if form.notebook_submission}
    <label class="line">
      <span>Notebook points<small>0 makes it a receipt</small></span>
      <input type="number" min="0" step="1" bind:value={form.notebook_points} />
    </label>
  {/if}
  <label class="check">
    <input type="checkbox" bind:checked={form.log_checks} />
    <span>Record the checks students run<small>Their activity, before they submit</small></span>
  </label>
</fieldset>

<style>
  fieldset {
    border: 0;
    padding: 0;
    margin: 18px 0 0;
    min-width: 0;
  }
  legend {
    font-weight: 600;
    font-size: 15px;
    padding: 0;
    margin-bottom: 6px;
  }
  .line {
    display: grid;
    grid-template-columns: 140px minmax(0, 1fr);
    gap: 10px;
    align-items: center;
    margin: 8px 0;
    font-size: 14px;
  }
  small {
    display: block;
    font-size: 12px;
    color: var(--muted);
    line-height: 1.3;
  }
  .envs {
    display: flex;
    gap: 14px;
    flex-wrap: wrap;
  }
  .envs label {
    display: inline-flex;
    align-items: center;
  }
  .check {
    display: flex;
    align-items: flex-start;
    gap: 2px;
    margin: 10px 0;
    font-size: 14px;
  }
  .check input {
    margin-top: 3px;
  }
  @media (max-width: 420px) {
    .line {
      grid-template-columns: 1fr;
      gap: 4px;
    }
  }
</style>
