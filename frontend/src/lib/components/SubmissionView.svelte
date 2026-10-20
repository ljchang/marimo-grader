<script lang="ts">
  // What a grader reads for one attempt: the worker's render (code above each
  // output) when the assignment re-runs submissions, with the submitted source a
  // click away; otherwise just the source. Either way, the files the student saved
  // under storage.private()/<slug>/ -- the hand-in for notebooks too heavy to
  // re-run -- flagged when they changed after the deadline.
  import { api, errorMessage, type Submission, type SubmissionFiles } from '$lib/api';
  import { fmtDateTime } from '$lib/format';
  import RenderFrame from './RenderFrame.svelte';

  let { submission, height = '100%' }: { submission: Submission; height?: string } = $props();

  let code = $state<string | null>(null);
  let files = $state<SubmissionFiles | null>(null);
  let error = $state<string | null>(null);

  const rerun = $derived(submission.renders !== false);
  let tab = $state<'render' | 'code'>('render');
  const showCode = $derived(!rerun || tab === 'code');

  // A new attempt starts on the render; the source is fetched once, when first shown.
  $effect(() => {
    void submission.id;
    tab = 'render';
    code = null;
  });

  $effect(() => {
    const id = submission.id;
    if (!showCode || code !== null) return;
    const ctl = new AbortController();
    api.submissions
      .notebook(id, ctl.signal)
      .then((t) => (code = t))
      .catch((e) => (error = errorMessage(e)));
    return () => ctl.abort();
  });

  $effect(() => {
    const id = submission.id;
    files = null;
    error = null;
    const ctl = new AbortController();
    api.submissions
      .files(id, ctl.signal)
      .then((f) => (files = f))
      .catch((e) => (error = errorMessage(e)));
    return () => ctl.abort();
  });

  const isImage = (path: string) => /\.(png|jpe?g|gif|svg|webp)$/i.test(path);

  function fmtSize(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / 1024 / 1024).toFixed(1)} MB`;
  }
</script>

<div class="view" style:height>
  {#if files && files.files.length > 0}
    <section class="files">
      <h3>Saved files <span class="muted mono small">{files.prefix}</span></h3>
      <ul>
        {#each files.files as f (f.path)}
          <li class:late={f.after_deadline}>
            {#if isImage(f.path)}
              <a href={f.url} target="_blank" rel="noopener noreferrer" data-native><img src={f.url} alt={f.path} loading="lazy" referrerpolicy="no-referrer" /></a>
            {/if}
            <a class="mono small" href={f.url} target="_blank" rel="noopener noreferrer" data-native>{f.path}</a>
            <span class="muted small">{fmtSize(f.size)}, {fmtDateTime(f.modified)}</span>
            {#if f.after_deadline}<span class="flag small">changed after the deadline</span>
            {:else if f.after_submission}<span class="muted small">changed after this attempt</span>{/if}
          </li>
        {/each}
      </ul>
    </section>
  {/if}

  {#if error}<p class="muted small">{error}</p>{/if}

  {#if rerun}
    <div class="tabs" role="tablist" aria-label="Submission view">
      <button role="tab" aria-selected={tab === 'render'} class:on={tab === 'render'} onclick={() => (tab = 'render')}>Rendered</button>
      <button role="tab" aria-selected={tab === 'code'} class:on={tab === 'code'} onclick={() => (tab = 'code')}>Code</button>
    </div>
  {/if}

  {#if showCode}
    <section class="code">
      {#if !rerun}<h3>Submitted notebook <span class="muted small">(not re-run for this assignment)</span></h3>{/if}
      {#if code === null}
        <p class="muted small">Loading…</p>
      {:else}
        <pre class="mono"><code>{code}</code></pre>
      {/if}
    </section>
  {:else}
    <div class="render">
      <RenderFrame src={submission.render_url} title="Submission by {submission.netid}" height="100%" />
    </div>
  {/if}
</div>

<style>
  .view {
    display: flex;
    flex-direction: column;
    gap: 10px;
    min-height: 0;
  }
  .tabs {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--rule);
  }
  .tabs button {
    font: inherit;
    font-size: 13px;
    padding: 4px 12px;
    border: 0;
    border-bottom: 2px solid transparent;
    background: none;
    color: var(--muted);
    cursor: pointer;
  }
  .tabs button.on {
    color: var(--ink);
    border-bottom-color: var(--accent);
  }
  .render {
    flex: 1;
    min-height: 420px;
  }
  .files ul {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 8px;
  }
  .files li {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: 6px 8px;
    border: 1px solid var(--rule);
    border-radius: var(--radius);
    overflow-wrap: anywhere;
  }
  .files li.late {
    border-color: var(--warn);
    background: var(--warn-soft);
  }
  .files img {
    width: 100%;
    max-height: 160px;
    object-fit: contain;
    background: var(--surface);
  }
  .flag {
    color: var(--warn);
    font-weight: 600;
  }
  .code {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .code pre {
    flex: 1;
    margin: 0;
    overflow: auto;
    padding: 10px 12px;
    border: 1px solid var(--rule);
    border-radius: var(--radius);
    background: var(--surface);
    font-size: 13px;
    line-height: 1.45;
    white-space: pre;
  }
  .code pre code {
    padding: 0;
    background: none;
    border: 0;
    font-size: inherit;
  }
  h3 {
    margin: 0 0 6px;
  }
</style>
