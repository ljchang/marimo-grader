<script lang="ts">
  import type { CellState, SubmissionStatus } from '$lib/api';
  import { fmtPoints } from '$lib/format';

  let {
    state,
    points = null,
    max = null,
  }: { state: CellState | SubmissionStatus; points?: number | null; max?: number | null } = $props();

  const label = $derived.by(() => {
    switch (state) {
      case 'none':
        return '·';
      case 'graded':
        return points !== null ? fmtPoints(points, max) : 'graded';
      case 'awaiting_manual':
        return 'awaiting';
      case 'failed':
        return 'failed';
      default:
        return state;
    }
  });
</script>

<span class="chip {state}" title={state}>{label}</span>
