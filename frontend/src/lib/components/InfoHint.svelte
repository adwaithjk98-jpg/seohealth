<script>
  import { fade } from 'svelte/transition';

  // Small accessible "(i)" affordance. Tap/click to toggle a popover (hover
  // isn't enough on touch, which is the primary device here). Closes on
  // Escape or an outside tap. Pass the explanation as the default slot.
  /**
   * @type {{
   *   label?: string,
   *   align?: 'left' | 'right',
   *   children: import('svelte').Snippet
   * }}
   */
  let { label = 'More info', align = 'left', children } = $props();

  let open = $state(false);

  /** @param {MouseEvent} e */
  function toggle(e) {
    e.stopPropagation();
    open = !open;
  }

  $effect(() => {
    if (!open) return;
    const onDoc = () => (open = false);
    /** @param {KeyboardEvent} e */
    const onKey = (e) => {
      if (e.key === 'Escape') open = false;
    };
    document.addEventListener('click', onDoc);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('click', onDoc);
      document.removeEventListener('keydown', onKey);
    };
  });
</script>

<span class="relative inline-flex align-middle">
  <button
    type="button"
    class="grid h-4 w-4 place-items-center rounded-full border border-canvas-muted/40 text-[10px] font-semibold leading-none text-canvas-muted transition-colors hover:border-healthy-300 hover:text-healthy-700"
    aria-label={label}
    aria-expanded={open}
    onclick={toggle}
  >
    i
  </button>
  {#if open}
    <span
      role="tooltip"
      class={`absolute top-6 z-30 w-60 rounded-xl border border-canvas-soft bg-white p-3 text-left text-xs font-normal leading-relaxed text-canvas-muted shadow-soft ${
        align === 'right' ? 'right-0' : 'left-0'
      }`}
      transition:fade={{ duration: 140 }}
    >
      {@render children()}
    </span>
  {/if}
</span>
