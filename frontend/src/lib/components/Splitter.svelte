<script lang="ts">
  // A drag handle between two panes. `value` is the size in px of the pane it
  // resizes; dragging, arrow keys and a double-click (back to `initial`) change it,
  // and the last size is kept in localStorage under `storageKey`. While dragging,
  // iframes stop taking pointer events, or the rendered notebook would swallow the
  // drag the moment the cursor crossed into it.
  import { onMount } from 'svelte';

  let {
    value = $bindable(),
    initial,
    min,
    max,
    orientation = 'vertical',
    invert = false,
    storageKey,
    measure,
    label,
  }: {
    /** Size in px of the pane being resized; null until set (the pane sizes itself). */
    value: number | null;
    /** What a double-click restores: a size, or null for the pane's natural size. */
    initial: number | null;
    min: number;
    /** Upper bound, read at drag time so it can follow the window. */
    max: () => number;
    /** 'vertical': a bar between columns (resizes a width); 'horizontal': between rows. */
    orientation?: 'vertical' | 'horizontal';
    /** Dragging toward the start (left/up) grows the pane: it sits after the handle. */
    invert?: boolean;
    storageKey?: string;
    /** The pane's current size, used when a drag starts from value === null. */
    measure?: () => number;
    label: string;
  } = $props();

  let dragging = $state(false);
  let startPos = 0;
  let startSize = 0;

  const clamp = (v: number) => Math.round(Math.max(min, Math.min(Math.max(min, max()), v)));

  function save() {
    if (!storageKey) return;
    try {
      if (value == null) localStorage.removeItem(storageKey);
      else localStorage.setItem(storageKey, String(value));
    } catch {
      // storage blocked: the size just won't outlive the page
    }
  }

  onMount(() => {
    if (!storageKey) return;
    try {
      const raw = localStorage.getItem(storageKey);
      const n = raw == null ? NaN : Number(raw);
      if (Number.isFinite(n)) value = clamp(n);
    } catch {
      // ignore
    }
  });

  const pos = (e: PointerEvent) => (orientation === 'vertical' ? e.clientX : e.clientY);

  function down(e: PointerEvent) {
    if (e.button !== 0) return;
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragging = true;
    startPos = pos(e);
    startSize = value ?? measure?.() ?? min;
    document.documentElement.classList.add('resizing', `resizing-${orientation}`);
  }

  function move(e: PointerEvent) {
    if (!dragging) return;
    const delta = pos(e) - startPos;
    value = clamp(startSize + (invert ? -delta : delta));
  }

  function up(e: PointerEvent) {
    if (!dragging) return;
    dragging = false;
    (e.currentTarget as HTMLElement).releasePointerCapture?.(e.pointerId);
    document.documentElement.classList.remove('resizing', `resizing-${orientation}`);
    save();
  }

  function key(e: KeyboardEvent) {
    const grow = orientation === 'vertical' ? (invert ? 'ArrowLeft' : 'ArrowRight') : invert ? 'ArrowUp' : 'ArrowDown';
    const shrink = orientation === 'vertical' ? (invert ? 'ArrowRight' : 'ArrowLeft') : invert ? 'ArrowDown' : 'ArrowUp';
    const step = e.shiftKey ? 80 : 20;
    if (e.key !== grow && e.key !== shrink) return;
    e.preventDefault();
    e.stopPropagation();
    const base = value ?? measure?.() ?? min;
    value = clamp(base + (e.key === grow ? step : -step));
    save();
  }

  function reset() {
    value = initial == null ? null : clamp(initial);
    save();
  }
</script>

<!-- A focusable separator is a widget (ARIA), which the a11y lint does not know. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
<div
  class="splitter {orientation}"
  class:dragging
  role="separator"
  aria-orientation={orientation}
  aria-label={label}
  aria-valuenow={value ?? undefined}
  aria-valuemin={min}
  tabindex="0"
  title="{label}: drag to resize, double-click to reset"
  onpointerdown={down}
  onpointermove={move}
  onpointerup={up}
  onpointercancel={up}
  ondblclick={reset}
  onkeydown={key}
></div>

<style>
  .splitter {
    position: relative;
    flex-shrink: 0;
    touch-action: none;
    z-index: 1;
  }
  .splitter.vertical {
    width: 7px;
    cursor: col-resize;
  }
  .splitter.horizontal {
    height: 7px;
    cursor: row-resize;
  }
  /* The visible rule, centred in a wider hit area. */
  .splitter::after {
    content: '';
    position: absolute;
    background: var(--rule);
    transition: background 0.12s;
  }
  .splitter.vertical::after {
    top: 0;
    bottom: 0;
    left: 3px;
    width: 1px;
  }
  .splitter.horizontal::after {
    left: 0;
    right: 0;
    top: 3px;
    height: 1px;
  }
  .splitter:hover::after,
  .splitter:focus-visible::after,
  .splitter.dragging::after {
    background: var(--accent);
  }
  .splitter.vertical:hover::after,
  .splitter.vertical:focus-visible::after,
  .splitter.vertical.dragging::after {
    left: 2px;
    width: 3px;
  }
  .splitter.horizontal:hover::after,
  .splitter.horizontal:focus-visible::after,
  .splitter.horizontal.dragging::after {
    top: 2px;
    height: 3px;
  }
  .splitter:focus-visible {
    outline: none;
  }
  :global(html.resizing iframe) {
    pointer-events: none;
  }
  :global(html.resizing),
  :global(html.resizing *) {
    user-select: none;
  }
  :global(html.resizing-vertical),
  :global(html.resizing-vertical *) {
    cursor: col-resize !important;
  }
  :global(html.resizing-horizontal),
  :global(html.resizing-horizontal *) {
    cursor: row-resize !important;
  }
</style>
