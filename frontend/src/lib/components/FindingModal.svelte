<script>
  import { onDestroy, onMount } from 'svelte';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { patchRecommendation } from '$lib/api.js';
  import {
    severityLabel,
    severityTone,
    impactLabel
  } from '$lib/dashboard.js';
  import { splitRecommendationBody, renderMarkdown } from '$lib/markdown.js';

  /**
   * @type {{
   *   recommendation: any,
   *   sectionLabel?: string,
   *   sectionEmoji?: string,
   *   onClose: () => void,
   *   onUpdate?: (rec: any) => void
   * }}
   */
  let {
    recommendation,
    sectionLabel = '',
    sectionEmoji = '',
    onClose,
    onUpdate = () => {}
  } = $props();

  const parts = $derived(splitRecommendationBody(recommendation?.body_markdown));
  const why = $derived(parts.why);
  const howSteps = $derived(parts.howSteps);
  const fallbackBodyHtml = $derived(
    !why && !howSteps.length ? renderMarkdown(recommendation?.body_markdown ?? '') : ''
  );

  const sevTone = $derived(severityTone(recommendation?.severity));
  const severityClasses = {
    healthy: 'bg-healthy-50 text-healthy-700',
    attention: 'bg-attention-50 text-attention-700',
    action: 'bg-action-50 text-action-700',
    muted: 'bg-canvas-soft text-canvas-muted'
  };

  let saving = $state(false);
  let saveError = $state(/** @type {string | null} */ (null));

  const isDone = $derived(recommendation?.fix_status === 'done');

  async function toggleDone() {
    if (!recommendation) return;
    saving = true;
    saveError = null;
    try {
      const next = isDone ? 'open' : 'done';
      const updated = await patchRecommendation(recommendation.id, next);
      onUpdate(updated);
    } catch (err) {
      saveError = err instanceof Error ? err.message : 'Could not save just yet.';
    } finally {
      saving = false;
    }
  }

  function onKey(event) {
    if (event.key === 'Escape') onClose();
  }

  onMount(() => {
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
  });

  onDestroy(() => {
    document.removeEventListener('keydown', onKey);
    document.body.style.overflow = '';
  });
</script>

<div
  class="fixed inset-0 z-50 flex items-end justify-center bg-canvas-ink/40 px-3 py-6 sm:items-center sm:py-12"
  in:fade={{ duration: 200 }}
  out:fade={{ duration: 150 }}
  onclick={onClose}
  role="presentation"
>
  <div
    class="relative w-full max-w-2xl overflow-hidden rounded-3xl bg-white shadow-soft"
    in:fly={{ y: 16, duration: 320, easing: quintOut }}
    out:fly={{ y: 12, duration: 200 }}
    onclick={(e) => e.stopPropagation()}
    role="dialog"
    aria-modal="true"
    aria-label={recommendation?.title ?? 'Recommendation'}
  >
    <button
      type="button"
      onclick={onClose}
      class="absolute right-4 top-4 grid h-9 w-9 place-items-center rounded-full bg-canvas-soft text-canvas-muted transition hover:bg-canvas-soft/80 hover:text-canvas-ink"
      aria-label="Close"
    >
      ✕
    </button>

    <div class="max-h-[85vh] overflow-y-auto p-6 sm:p-8">
      <div class="flex flex-wrap items-center gap-2 text-xs text-canvas-muted">
        {#if sectionEmoji || sectionLabel}
          <span class="inline-flex items-center gap-1">
            <span aria-hidden="true">{sectionEmoji}</span>
            {sectionLabel}
          </span>
        {/if}
        <span
          class={`rounded-full px-2 py-0.5 font-medium ${severityClasses[sevTone]}`}
        >
          {severityLabel(recommendation?.severity)}
        </span>
        {#if isDone}
          <span class="rounded-full bg-healthy-50 px-2 py-0.5 font-medium text-healthy-700">
            ✓ Done
          </span>
        {/if}
      </div>

      <h2 class="mt-3 text-2xl font-semibold tracking-tight text-canvas-ink">
        {recommendation?.title}
      </h2>

      {#if why}
        <section class="mt-5">
          <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
            Why it matters
          </p>
          <p class="mt-2 text-sm leading-relaxed text-canvas-ink">{why}</p>
        </section>
      {/if}

      <section class="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3">
        <div class="rounded-2xl bg-canvas-soft px-3 py-3">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-canvas-muted">
            Impact
          </p>
          <p class="mt-1 text-sm font-medium text-canvas-ink">
            {impactLabel(recommendation?.estimated_impact) ?? '—'}
          </p>
        </div>
        <div class="rounded-2xl bg-canvas-soft px-3 py-3">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-canvas-muted">
            Time
          </p>
          <p class="mt-1 text-sm font-medium text-canvas-ink">
            {recommendation?.estimated_time ?? '—'}
          </p>
        </div>
        <div class="rounded-2xl bg-canvas-soft px-3 py-3">
          <p class="text-[10px] font-semibold uppercase tracking-wide text-canvas-muted">
            Difficulty
          </p>
          <p class="mt-1 text-sm font-medium text-canvas-ink">
            {recommendation?.estimated_time === 'professional help' ? 'Get a hand' : 'Beginner-friendly'}
          </p>
        </div>
      </section>

      {#if howSteps.length > 0}
        <section class="mt-6">
          <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
            How to fix it
          </p>
          <ol class="mt-3 space-y-3">
            {#each howSteps as step, i}
              <li class="flex items-start gap-3">
                <span
                  class="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-healthy-50 text-xs font-semibold text-healthy-700"
                  aria-hidden="true"
                >
                  {i + 1}
                </span>
                <p class="text-sm leading-relaxed text-canvas-ink">
                  {@html renderMarkdown(step)
                    .replace(/^<p>/, '')
                    .replace(/<\/p>$/, '')}
                </p>
              </li>
            {/each}
          </ol>
        </section>
      {:else if fallbackBodyHtml}
        <section class="prose prose-sm mt-6 max-w-none text-canvas-ink">
          {@html fallbackBodyHtml}
        </section>
      {/if}

      {#if saveError}
        <p class="mt-5 rounded-xl bg-action-50 px-3 py-2 text-sm text-action-700">{saveError}</p>
      {/if}

      <div class="mt-7 flex flex-col-reverse gap-3 border-t border-canvas-soft pt-5 sm:flex-row sm:items-center sm:justify-between">
        <p class="text-xs text-canvas-muted">
          {#if isDone}
            Marked done. We'll re-check this on your next audit.
          {:else}
            Take 5 minutes when you can — small steps add up.
          {/if}
        </p>
        <button
          type="button"
          class={isDone ? 'btn-ghost' : 'btn-primary'}
          disabled={saving}
          onclick={toggleDone}
        >
          {#if saving}
            Saving…
          {:else if isDone}
            ↺ Mark as not done
          {:else}
            ✓ Mark as done
          {/if}
        </button>
      </div>
    </div>
  </div>
</div>
