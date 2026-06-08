<script>
  import { fade, fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';
  import { reduced } from '$lib/motion.js';

  /**
   * @type {{
   *   data: {
   *     confirmed: Array<any>,
   *     unverified_done: Array<any>,
   *     new: Array<any>,
   *     prev_finished_at: string | null
   *   }
   * }}
   *
   * Shows three small counters: confirmed fixes, marked-done-but-still-
   * not-seen, and new findings. Hides itself entirely when there's no
   * prior audit (``prev_finished_at`` null) or when all three buckets
   * are empty — silent first-week of usage rather than a dead strip.
   */
  let { data } = $props();

  const visible = $derived(
    !!data?.prev_finished_at &&
      (data.confirmed.length + data.unverified_done.length + data.new.length) > 0
  );

  const confirmedCount = $derived(data?.confirmed.length ?? 0);
  const unverifiedCount = $derived(data?.unverified_done.length ?? 0);
  const newCount = $derived(data?.new.length ?? 0);

  let expanded = $state(false);
</script>

{#if visible}
  <section
    class="card border border-healthy-100 bg-healthy-50/40 p-4 sm:p-5"
    in:fade={reduced({ duration: 200 })}
    aria-labelledby="since-last-check-heading"
  >
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0">
        <p id="since-last-check-heading" class="text-sm font-semibold text-canvas-ink">
          Since your last check
        </p>
        <ul class="mt-2 flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-canvas-muted">
          {#if confirmedCount > 0}
            <li class="inline-flex items-center gap-1.5">
              <span class="text-healthy-600" aria-hidden="true">✓</span>
              <span class="text-canvas-ink">
                <strong class="font-semibold text-healthy-700">{confirmedCount}</strong>
                fix{confirmedCount === 1 ? '' : 'es'} confirmed
              </span>
            </li>
          {/if}
          {#if unverifiedCount > 0}
            <li class="inline-flex items-center gap-1.5">
              <span class="text-attention-600" aria-hidden="true">!</span>
              <span class="text-canvas-ink">
                <strong class="font-semibold text-attention-700">{unverifiedCount}</strong>
                marked done but not seen
              </span>
            </li>
          {/if}
          {#if newCount > 0}
            <li class="inline-flex items-center gap-1.5">
              <span class="text-canvas-muted" aria-hidden="true">⊕</span>
              <span class="text-canvas-ink">
                <strong class="font-semibold text-canvas-ink">{newCount}</strong>
                new thing{newCount === 1 ? '' : 's'} to look at
              </span>
            </li>
          {/if}
        </ul>
      </div>
      {#if confirmedCount > 0 || unverifiedCount > 0 || newCount > 0}
        <button
          type="button"
          class="btn-ghost text-xs"
          aria-expanded={expanded}
          onclick={() => (expanded = !expanded)}
        >
          {expanded ? 'Hide details' : 'See details'}
        </button>
      {/if}
    </div>

    {#if expanded}
      <div
        class="mt-4 space-y-3 text-xs"
        in:fly={reduced({ y: 4, duration: 180, easing: quintOut })}
      >
        {#if confirmedCount > 0}
          <div>
            <p class="font-medium text-healthy-700">Confirmed fixes</p>
            <ul class="mt-1 space-y-1 text-canvas-ink">
              {#each data.confirmed as item}
                <li class="flex items-start gap-2">
                  <span class="text-healthy-600" aria-hidden="true">✓</span>
                  <span>{item.title}</span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}
        {#if unverifiedCount > 0}
          <div>
            <p class="font-medium text-attention-700">Marked done but not yet detected</p>
            <ul class="mt-1 space-y-1 text-canvas-ink">
              {#each data.unverified_done as item}
                <li class="flex items-start gap-2">
                  <span class="text-attention-600" aria-hidden="true">!</span>
                  <span>{item.title}</span>
                </li>
              {/each}
            </ul>
            <p class="mt-1 text-canvas-muted">
              We still don't see the underlying signal. Double-check the change is live,
              or re-run the audit if you just shipped it.
            </p>
          </div>
        {/if}
        {#if newCount > 0}
          <div>
            <p class="font-medium text-canvas-ink">New findings this audit</p>
            <ul class="mt-1 space-y-1 text-canvas-ink">
              {#each data.new as item}
                <li class="flex items-start gap-2">
                  <span class="text-canvas-muted" aria-hidden="true">⊕</span>
                  <span>{item.title}</span>
                </li>
              {/each}
            </ul>
          </div>
        {/if}
      </div>
    {/if}
  </section>
{/if}
