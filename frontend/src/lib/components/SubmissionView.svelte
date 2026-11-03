<script lang="ts">
  // What a grader reads for one attempt: a render (code above each output) with the
  // submitted source a click away. The render is the student's own outputs, taken
  // from marimo's session snapshot without running anything, until the worker's
  // re-run replaces it (for assignments that re-run); the label says which. With no
  // render at all, just the source. Either way, the files the student saved under
  // storage.private()/<slug>/, flagged when they changed after the deadline.
  import { api, errorMessage, type RenderInfo, type Submission, type SubmissionFiles } from '$lib/api';
  import { fmtDateTime } from '$lib/format';
  import RenderFrame from './RenderFrame.svelte';

  let {
    submission,
    height = '100%',
    own = false,
  }: { submission: Submission; height?: string; own?: boolean } = $props();

  let code = $state<string | null>(null);
  let files = $state<SubmissionFiles | null>(null);
  let error = $state<string | null>(null);

  const rerun = $derived(submission.renders !== false);
  // Something for the Rendered tab: a render exists, or a re-run is on its way.
  const renders = $derived(rerun || !!submission.render_url);
  let tab = $state<'render' | 'code'>('render');
  const showCode = $derived(!renders || tab === 'code');
  const label = $derived(renderLabel(submission.render_info, own));

  function cells(i: RenderInfo): string {
    if (i.matched == null || i.total == null) return '';
    if (i.matched === i.total) return `all ${i.total} cells`;
    return `${i.matched} of ${i.total} cells (a cell edited after it last ran shows its code only)`;
  }

  /** Headline and detail for the render, or null when there is nothing to say. */
  function renderLabel(i: RenderInfo | null | undefined, own: boolean): [string, string] | null {
    if (!i) return null;
    const whose = own ? 'Your own outputs' : "The student's own outputs";
    if (i.source === 'snapshot') {
      if (i.snapshot === 'attached') return ['Outputs attached by the instructor', cells(i)];
      return [`${whose}, saved with this attempt`, cells(i)];
    }
    if (i.source === 'attached') return ['Render attached by the instructor', ''];
    return ['Re-run by the grader', ''];
  }

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

  {#if renders}
    <div class="tabs" role="tablist" aria-label="Submission view">
      <button role="tab" aria-selected={tab === 'render'} class:on={tab === 'render'} onclick={() => (tab = 'render')}>Rendered</button>
      <button role="tab" aria-selected={tab === 'code'} class:on={tab === 'code'} onclick={() => (tab = 'code')}>Code</button>
      {#if label && tab === 'render'}
        <span class="source small" class:own={submission.render_info?.source === 'snapshot'}>
          {label[0]}{#if label[1]}<span class="muted">{' · '}{label[1]}</span>{/if}
        </span>
      {/if}
    </div>
  {/if}

  {#if showCode}
    <section class="code">
      {#if !renders}<h3>Submitted notebook <span class="muted small">(not re-run for this assignment)</span></h3>{/if}
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
  .source {
    margin-left: auto;
    align-self: center;
    padding: 2px 8px;
    border-radius: var(--radius);
    color: var(--muted);
  }
  .source.own {
    color: var(--ink);
    background: var(--accent-soft);
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
