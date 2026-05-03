<script>
  import { scoreTone, scoreLabel } from '$lib/dashboard.js';

  /** @type {{ section: any, href: string }} */
  let { section, href } = $props();

  const tone = $derived(scoreTone(section?.score));
  const score = $derived(section?.score);
  const openCount = $derived(
    (section?.recommendations ?? []).filter((r) => r.fix_status === 'open').length
  );

  const ringClass = $derived(
    {
      healthy: 'border-healthy-200 hover:border-healthy-300',
      attention: 'border-attention-200 hover:border-attention-300',
      action: 'border-action-200 hover:border-action-300',
      muted: 'border-canvas-soft hover:border-canvas-muted/40'
    }[tone]
  );

  const accentBg = $derived(
    {
      healthy: 'bg-healthy-50 text-healthy-700',
      attention: 'bg-attention-50 text-attention-700',
      action: 'bg-action-50 text-action-700',
      muted: 'bg-canvas-soft text-canvas-muted'
    }[tone]
  );
</script>

<a
  {href}
  class={`card flex h-full flex-col gap-3 border p-5 transition hover:shadow-soft ${ringClass}`}
>
  <div class="flex items-start justify-between gap-3">
    <div class="flex items-center gap-3">
      <span
        class="grid h-10 w-10 place-items-center rounded-xl bg-canvas-soft text-lg"
        aria-hidden="true"
      >
        {section.emoji}
      </span>
      <div>
        <p class="text-sm font-medium text-canvas-ink">{section.label}</p>
        <p class="text-xs text-canvas-muted">{section.tagline}</p>
      </div>
    </div>
    <span class={`rounded-full px-2 py-0.5 text-xs font-medium ${accentBg}`}>
      {section.grade}
    </span>
  </div>

  <div class="flex items-end justify-between">
    <div>
      <p class="text-3xl font-semibold tracking-tight text-canvas-ink">
        {score == null ? '—' : score}
        <span class="text-base font-normal text-canvas-muted">/100</span>
      </p>
      <p class="text-xs text-canvas-muted">{scoreLabel(score)}</p>
    </div>
    <div class="text-right text-xs text-canvas-muted">
      {#if section.summary}
        <p>{section.summary}</p>
      {/if}
      {#if openCount > 0}
        <p class="mt-1 text-canvas-ink">
          {openCount} thing{openCount === 1 ? '' : 's'} to look at →
        </p>
      {:else}
        <p class="mt-1 text-healthy-700">All caught up ✓</p>
      {/if}
    </div>
  </div>
</a>
