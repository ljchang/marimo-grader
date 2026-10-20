<script lang="ts">
  // A panel that slides in from the right over the page, for work that belongs
  // to one assignment (its settings, a corrected notebook) without leaving the
  // list or the page underneath. Escape or a click outside closes it.
  import { tick, type Snippet } from 'svelte';

  let {
    title,
    subtitle,
    onclose,
    children,
    footer,
  }: {
    title: string;
    subtitle?: string;
    onclose: () => void;
    children: Snippet;
    footer?: Snippet;
  } = $props();

  let panel = $state<HTMLElement | null>(null);
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;

  $effect(() => {
    void tick().then(() => panel?.querySelector<HTMLElement>('input, select, textarea, button')?.focus());
    return () => opener?.focus();
  });

  function onkeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') {
      e.stopPropagation();
      onclose();
    }
  }
</script>

<svelte:window {onkeydown} />

<div class="scrim" onclick={onclose} aria-hidden="true"></div>
<div class="drawer" role="dialog" aria-modal="true" aria-label={title} bind:this={panel}>
  <header>
    <h2>{title}</h2>
    {#if subtitle}<p>{subtitle}</p>{/if}
  </header>
  <div class="body">{@render children()}</div>
  {#if footer}<footer>{@render footer()}</footer>{/if}
</div>

<style>
  .scrim {
    position: fixed;
    inset: 0;
    z-index: 40;
    background: rgba(5, 8, 5, 0.5);
  }
  .drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    z-index: 41;
    width: min(460px, 100vw);
    display: flex;
    flex-direction: column;
    background: var(--paper);
    border-left: 1px solid var(--rule);
    box-shadow: -24px 0 48px rgba(0, 0, 0, 0.3);
    animation: slide 160ms ease-out;
  }
  @keyframes slide {
    from {
      transform: translateX(24px);
      opacity: 0;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .drawer {
      animation: none;
    }
  }
  header {
    padding: 18px 22px 12px;
    border-bottom: 1px solid var(--rule);
  }
  header h2 {
    margin: 0;
    font-size: 19px;
  }
  header p {
    margin: 2px 0 0;
    font-size: 13px;
    color: var(--muted);
  }
  .body {
    flex: 1;
    overflow: auto;
    padding: 4px 22px 22px;
  }
  footer {
    display: flex;
    gap: 8px;
    align-items: center;
    padding: 14px 22px;
    border-top: 1px solid var(--rule);
  }
</style>
