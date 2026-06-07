<script>
  // Shared, never-invasive upgrade nudge. Two tones enforce the product rule
  // that Pro and Max nudges are visually distinct:
  //   - tone="pro": prominent, inviting (green gradient + primary CTA). The
  //     Free -> Pro growth priority.
  //   - tone="max": low-key, factual (muted card + ghost CTA). Only ever shown
  //     at a hit capacity limit; never persuasive, never a banner.
  // It is a static element the user can ignore — it opens nothing on its own.

  /**
   * @type {{
   *   tone?: 'pro' | 'max',
   *   eyebrow?: string,
   *   title: string,
   *   body?: string,
   *   cta?: string,
   *   href?: string
   * }}
   */
  let {
    tone = 'pro',
    eyebrow = '',
    title,
    body = '',
    cta = 'See plans',
    href = '/billing'
  } = $props();

  const isPro = $derived(tone === 'pro');
</script>

<div
  class={`card flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between ${
    isPro
      ? 'border-healthy-100 bg-gradient-to-br from-healthy-50/70 to-white'
      : 'border-canvas-soft bg-canvas-soft/30'
  }`}
>
  <div class="min-w-0">
    {#if eyebrow}
      <p
        class={`inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide ${
          isPro ? 'text-healthy-700' : 'text-canvas-muted'
        }`}
      >
        <span class={`h-1.5 w-1.5 rounded-full ${isPro ? 'bg-healthy-500' : 'bg-canvas-muted/60'}`}
        ></span>
        {eyebrow}
      </p>
    {/if}
    <p class={`text-sm ${isPro ? 'font-semibold' : 'font-medium'} text-canvas-ink`}>{title}</p>
    {#if body}
      <p class="mt-0.5 text-xs text-canvas-muted">{body}</p>
    {/if}
  </div>
  <a class={`${isPro ? 'btn-primary' : 'btn-ghost'} w-full shrink-0 sm:w-auto`} {href}>
    {cta}
  </a>
</div>
