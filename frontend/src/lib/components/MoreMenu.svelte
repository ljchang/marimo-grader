<script lang="ts" module>
  export interface MenuItem {
    label: string;
    onselect: () => void;
    disabled?: boolean;
  }
</script>

<script lang="ts">
  // The "More" button: the assignment actions used now and then. The list is
  // placed with fixed positioning so a scrolling table cannot clip it.
  import { tick } from 'svelte';

  let { items, label = 'More', ariaLabel }: { items: MenuItem[]; label?: string; ariaLabel?: string } = $props();

  let open = $state(false);
  let button = $state<HTMLButtonElement | null>(null);
  let list = $state<HTMLUListElement | null>(null);
  let pos = $state({ top: 0, right: 0 });

  async function toggle() {
    if (open) return close();
    const r = button!.getBoundingClientRect();
    pos = { top: r.bottom + 4, right: window.innerWidth - r.right };
    open = true;
    await tick();
    list?.querySelector<HTMLElement>('button:not(:disabled)')?.focus();
  }

  function close(refocus = true) {
    open = false;
    if (refocus) button?.focus();
  }

  function choose(item: MenuItem) {
    close();
    item.onselect();
  }

  function onkeydown(e: KeyboardEvent) {
    const buttons = [...(list?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') ?? [])];
    const i = buttons.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === 'Escape') {
      e.preventDefault();
      close();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      buttons[(i + 1) % buttons.length]?.focus();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      buttons[(i - 1 + buttons.length) % buttons.length]?.focus();
    } else if (e.key === 'Tab') {
      close(false);
    }
  }

  function onwindow(e: Event) {
    if (!open) return;
    if (e.type === 'pointerdown' && (list?.contains(e.target as Node) || button?.contains(e.target as Node))) return;
    close(false);
  }
</script>

<svelte:window onpointerdown={onwindow} onresize={onwindow} onscrollcapture={onwindow} />

<button class="more" bind:this={button} onclick={toggle} aria-haspopup="menu" aria-expanded={open} aria-label={ariaLabel}>{label}</button>
{#if open}
  <ul class="menu" role="menu" bind:this={list} style:top="{pos.top}px" style:right="{pos.right}px" {onkeydown}>
    {#each items as item (item.label)}
      <li role="none"><button role="menuitem" disabled={item.disabled} onclick={() => choose(item)}>{item.label}</button></li>
    {/each}
  </ul>
{/if}

<style>
  .menu {
    position: fixed;
    z-index: 30;
    list-style: none;
    margin: 0;
    padding: 4px 0;
    min-width: 210px;
    background: var(--surface);
    border: 1px solid var(--rule);
    border-radius: var(--radius);
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.3);
  }
  .menu button {
    display: block;
    width: 100%;
    text-align: left;
    border: 0;
    border-radius: 0;
    background: none;
    padding: 8px 14px;
    white-space: nowrap;
  }
  .menu button:hover,
  .menu button:focus-visible {
    background: var(--accent-soft);
    outline: none;
  }
</style>
