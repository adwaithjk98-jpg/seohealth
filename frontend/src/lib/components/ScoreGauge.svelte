<script>
  import { onMount } from 'svelte';
  import {
    scoreLabel,
    scoreTone,
    trendArrow,
    trendTone,
    trendLabel
  } from '$lib/dashboard.js';

  /** @type {{
   *   score: number | null,
   *   grade?: string,
   *   size?: number,
   *   label?: string,
   *   trend?: string | null,
   *   previousScore?: number | null
   * }} */
  let {
    score = null,
    grade = '',
    size = 220,
    label = '',
    trend = null,
    previousScore = null
  } = $props();

  const arrow = $derived(trendArrow(trend));
  const arrowTone = $derived(trendTone(trend));
  const arrowToneClass = $derived(
    {
      healthy: 'bg-healthy-50 text-healthy-700',
      attention: 'bg-attention-50 text-attention-700',
      action: 'bg-action-50 text-action-700',
      muted: 'bg-canvas-soft text-canvas-muted'
    }[arrowTone]
  );
  const trendCopy = $derived(trendLabel(score, previousScore, trend));

  // Animate the score up from 0 once the gauge mounts.
  let displayed = $state(0);

  onMount(() => {
    if (score == null) return;
    const target = score;
    const start = performance.now();
    const duration = 1100;
    let raf;
    const step = (now) => {
      const t = Math.min(1, (now - start) / duration);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3);
      displayed = Math.round(target * eased);
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  });

  const radius = $derived(size / 2 - 14);
  const circumference = $derived(2 * Math.PI * radius);
  const progress = $derived(score == null ? 0 : Math.max(0, Math.min(100, displayed)) / 100);
  const dashOffset = $derived(circumference * (1 - progress));

  const tone = $derived(scoreTone(score));
  const stroke = $derived(
    {
      healthy: '#4f8c5b',
      attention: '#c69423',
      action: '#d35a3f',
      muted: '#9a978d'
    }[tone]
  );
  const trackStroke = $derived(
    {
      healthy: '#e3efe5',
      attention: '#faedc9',
      action: '#fbe3da',
      muted: '#ece9e1'
    }[tone]
  );

  const friendly = $derived(score == null ? '' : scoreLabel(score));
</script>

<div class="flex flex-col items-center" style="width:{size}px">
  <svg width={size} height={size} viewBox="0 0 {size} {size}" aria-hidden="true">
    <circle
      cx={size / 2}
      cy={size / 2}
      r={radius}
      fill="none"
      stroke={trackStroke}
      stroke-width="14"
    />
    <circle
      cx={size / 2}
      cy={size / 2}
      r={radius}
      fill="none"
      stroke={stroke}
      stroke-width="14"
      stroke-linecap="round"
      stroke-dasharray={circumference}
      stroke-dashoffset={dashOffset}
      transform="rotate(-90 {size / 2} {size / 2})"
      style="transition: stroke 400ms ease;"
    />
  </svg>
  <div class="-mt-[60%] flex flex-col items-center" aria-live="polite">
    <p class="text-5xl font-semibold tracking-tight text-canvas-ink">
      {score == null ? '—' : displayed}
    </p>
    {#if grade}
      <p class="mt-1 text-sm font-medium text-canvas-muted">Grade {grade}</p>
    {/if}
    {#if label}
      <p class="mt-1 text-xs uppercase tracking-wide text-canvas-muted">{label}</p>
    {/if}
  </div>
  {#if friendly}
    <p class="mt-2 text-sm font-medium text-canvas-ink">{friendly}</p>
  {/if}
  {#if arrow}
    <div class="mt-2 flex items-center gap-2 text-xs">
      <span
        class={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${arrowToneClass}`}
        aria-label={trendCopy}
      >
        <span aria-hidden="true">{arrow}</span>
        {trend === 'up' ? 'Up' : trend === 'down' ? 'Down' : 'Steady'}
      </span>
      {#if trendCopy && trend !== 'flat'}
        <span class="text-canvas-muted">{trendCopy}</span>
      {/if}
    </div>
  {/if}
</div>
