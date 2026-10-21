<script lang="ts">
  // A question's rubric, written as an outline (see rubricText.ts) with the
  // items it makes shown underneath as they will appear in the grading queue.
  import { api, errorMessage, type Question } from '$lib/api';
  import { trim } from '$lib/format';
  import { formatRubric, groupRubric, parseRubric } from '$lib/rubricText';
  import Drawer from './Drawer.svelte';
  import Loading from './Loading.svelte';
  import Notice from './Notice.svelte';

  let {
    offeringId,
    question,
    onclose,
    onsaved,
  }: {
    offeringId: string;
    question: Question;
    onclose: () => void;
    onsaved: (message: string) => void;
  } = $props();

  const notebook = $derived(question.qid === 'notebook');
  const name = $derived(notebook ? 'Whole notebook' : question.qid);

  let text = $state('');
  let had = $state(false);
  let loaded = $state(false);
  let busy = $state(false);
  let error = $state<string | null>(null);

  $effect(() => {
    api.assignments
      .rubric(offeringId, question.id)
      .then((r) => {
        text = formatRubric(r.items);
        had = r.items.length > 0;
      })
      .catch((err) => (error = errorMessage(err)))
      .finally(() => (loaded = true));
  });

  const parsed = $derived(parseRubric(text));
  const groups = $derived(groupRubric(parsed.items));
  const total = $derived(parsed.items.reduce((sum, it) => sum + it.points, 0));

  async function save(items = parsed.items) {
    busy = true;
    error = null;
    try {
      const r = await api.assignments.setRubric(offeringId, question.id, items);
      onsaved(
        r.items.length
          ? `Saved the rubric for ${name}: ${r.items.length} items, ${trim(r.total)} points.`
          : `Removed the rubric for ${name}.`,
      );
    } catch (err) {
      error = errorMessage(err);
    } finally {
      busy = false;
    }
  }
</script>

<Drawer title="{name} rubric" subtitle="Only you and your TAs see it." {onclose}>
  {#if !loaded}
    <Loading />
  {:else}
    <form
      id="rubric-form"
      onsubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      {#if error}<Notice kind="error" label="Not saved">{error}</Notice>{/if}
      <p class="lead">
        In the grading queue you score each item, and the scores add up to the student's points.
        {#if notebook}The notebook is worth the rubric's total.{:else}The rubric can use up to {trim(question.max_points)} points.{/if}
      </p>
      <label class="field">
        <span>Outline<small>A line at the margin starts a part; indented lines under it are its items. Items are worth 1 point unless they end in “(2 points)”. A part with no items is scored as one.</small></span>
        <textarea
          bind:value={text}
          rows="14"
          spellcheck="false"
          placeholder={'Short answer (5 points)\nAnalysis\n    Load the data\n    Fit the model (2 points)'}
        ></textarea>
      </label>
      <p class="small muted">Scores are kept by position, so add new items at the end of a part once grading has started.</p>

      {#each parsed.errors as msg (msg)}<Notice kind="warn" label="Check">{msg}</Notice>{/each}

      {#if parsed.items.length}
        <h3><span>{parsed.items.length} {parsed.items.length === 1 ? 'item' : 'items'}</span><span class="num">{trim(total)} points</span></h3>
        <table class="preview">
          {#each groups as g, gi (gi)}
            <tbody>
              {#if g.label && !(g.items.length === 1 && g.items[0]?.label === g.label)}
                <tr class="part"><th colspan="2">{g.label}</th><td class="num">{trim(g.total)}</td></tr>
              {/if}
              {#each g.items as it (it.key)}
                <tr>
                  <td class="mono muted key">{it.key}</td>
                  <td>{it.label}</td>
                  <td class="num">{trim(it.points)}</td>
                </tr>
              {/each}
            </tbody>
          {/each}
        </table>
      {/if}
    </form>
  {/if}
  {#snippet footer()}
    <button
      class="primary"
      type="submit"
      form="rubric-form"
      disabled={busy || !loaded || parsed.errors.length > 0 || parsed.items.length === 0}
    >{busy ? 'Saving…' : 'Save rubric'}</button>
    {#if had}<button type="button" class="quiet danger" disabled={busy} onclick={() => save([])}>Remove rubric</button>{/if}
    <button class="quiet" type="button" onclick={onclose}>Cancel</button>
  {/snippet}
</Drawer>

<style>
  .lead {
    margin: 16px 0 12px;
    font-size: 14px;
  }
  .field {
    display: grid;
    gap: 6px;
    font-size: 14px;
  }
  .field small {
    display: block;
    color: var(--muted);
    font-size: 12px;
    margin-top: 2px;
  }
  textarea {
    font-family: var(--mono);
    font-size: 13px;
    line-height: 1.5;
    tab-size: 4;
  }
  h3 {
    display: flex;
    justify-content: space-between;
    font-size: 15px;
    margin: 20px 0 6px;
  }
  .preview {
    width: 100%;
    border-collapse: collapse;
    font-size: 14px;
  }
  .preview td,
  .preview th {
    padding: 4px 6px;
    border-bottom: 1px solid var(--rule);
    text-align: left;
    vertical-align: top;
  }
  .preview .part th,
  .preview .part td {
    padding-top: 12px;
    font-weight: 600;
  }
  .preview .key {
    width: 3.5em;
    font-size: 12px;
  }
  .preview td.num {
    text-align: right;
    width: 3em;
  }
  button.danger {
    color: var(--danger);
  }
</style>
