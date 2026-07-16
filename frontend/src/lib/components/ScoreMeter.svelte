<script>
  import { onMount } from 'svelte';
  import { prefersReducedMotion } from '$lib/motion.js';
  import {
    scoreLabel,
    scoreTone,
    trendArrow,
    trendTone,
    trendLabel
  } from '$lib/dashboard.js';

  /**
   * Stat tile + meter — the successor to the old ScoreGauge donut.
   * A score out of 100 is a single ratio against a limit, so the honest
   * form is a slim meter under a hero figure, not a ring: the number
   * carries the value, the bar carries the tone, and the trend pill
   * carries the movement. Nothing is said twice.
   *
   * @type {{
   *   score: number | null,
   *   label?: string,
   *   trend?: string | null,
   *   previousScore?: number | null,
   *   hero?: boolean
   * }}
   */
  let {
    score = null,
    label = '',
    trend = null,
    previousScore = null,
    hero = false
  } = $props();

  const arrow = $derived(trendArrow(trend));
  const arrowToneClass = $derived(
    {
      healthy: 'bg-healthy-50 text-healthy-700',
      attention: 'bg-attention-50 text-attention-700',
      action: 'bg-action-50 text-action-700',
      muted: 'bg-canvas-soft text-canvas-muted'
    }[trendTone(trend)]
  );
  const trendCopy = $derived(trendLabel(score, previousScore, trend));
  // The pill already says Up/Down/Steady; the visible companion text only
  // carries the size of the move (full sentence stays on aria-label).
  const deltaCopy = $derived.by(() => {
    if (score == null || previousScore == null) return null;
    const d = Math.abs(score - previousScore);
    if (d === 0 || trend === 'flat') return null;
    return `${d} point${d === 1 ? '' : 's'} since last check`;
  });

  // One rAF drives both the count-up figure and the meter fill, so the
  // number and the bar always agree mid-animation.
  let displayed = $state(0);

  onMount(() => {
    if (score == null) return;
    if (prefersReducedMotion()) {
      displayed = score;
      return;
    }
    const target = score;
    const start = performance.now();
    const duration = 1100;
    let raf = 0;
    const step = (/** @type {number} */ now) => {
      const t = Math.min(1, (now - start) / duration);
      // ease-out cubic
      const eased = 1 - Math.pow(1 - t, 3);
      displayed = Math.round(target * eased);
      if (t < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  });

  const pct = $derived(score == null ? 0 : Math.max(0, Math.min(100, displayed)));
  // A rounded fill thinner than its own radius renders as a squashed
  // blob, so a real-but-tiny score keeps a 0.5rem floor.
  const fillWidth = $derived(score == null || score === 0 ? '0' : `max(${pct}%, 0.5rem)`);

  const tone = $derived(scoreTone(score));
  // Meter rule: the fill carries the tone; the track is a lighter step of
  // the SAME ramp, so the state reads across the whole bar.
  const fillClass = $derived(
    {
      healthy: 'bg-healthy-500',
      attention: 'bg-attention-500',
      action: 'bg-action-500',
      muted: 'bg-canvas-muted/40'
    }[tone]
  );
  const trackClass = $derived(
    {
      healthy: 'bg-healthy-100',
      attention: 'bg-attention-100',
      action: 'bg-action-100',
      muted: 'bg-canvas-soft'
    }[tone]
  );

  const friendly = $derived(score == null ? '' : scoreLabel(score));
</script>

<div>
  {#if label}
    <p class="text-xs font-medium text-canvas-muted">{label}</p>
  {/if}

  <div class="mt-1 flex flex-wrap items-end justify-between gap-x-4 gap-y-1">
    <!-- The animated figure is decorative during the count-up; the sr-only
         line below is the stable, single announcement. -->
    <p aria-hidden="true" class="leading-none">
      <span
        class={`font-semibold tracking-tight text-canvas-ink ${hero ? 'text-6xl' : 'text-4xl'}`}
      >
        {score == null ? '—' : displayed}
      </span>
      {#if score != null}
        <span class={`font-normal text-canvas-muted ${hero ? 'text-xl' : 'text-base'}`}>/100</span>
      {/if}
    </p>
    <p class="sr-only">
      {label || 'Score'}: {score == null ? 'not available yet' : `${score} out of 100 — ${friendly}`}
    </p>

    {#if arrow}
      <div class="flex items-center gap-2 pb-0.5 text-xs">
        <span
          class={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${arrowToneClass}`}
          aria-label={trendCopy}
        >
          <span aria-hidden="true">{arrow}</span>
          {trend === 'up' ? 'Up' : trend === 'down' ? 'Down' : 'Steady'}
        </span>
        {#if deltaCopy}
          <span class="text-canvas-muted">{deltaCopy}</span>
        {/if}
      </div>
    {:else if score != null && previousScore == null}
      <p class="pb-0.5 text-xs text-canvas-muted">First check</p>
    {/if}
  </div>

  <div
    class={`mt-3 w-full overflow-hidden rounded-full ${hero ? 'h-2' : 'h-1.5'} ${trackClass}`}
    role="meter"
    aria-valuemin="0"
    aria-valuemax="100"
    aria-valuenow={score ?? undefined}
    aria-valuetext={score == null ? 'No score yet' : `${score} out of 100 — ${friendly}`}
    aria-label={label || 'Score'}
  >
    <div
      class={`h-full rounded-full ${fillClass}`}
      style={`width:${fillWidth};transition:background-color 400ms ease;`}
    ></div>
  </div>

  <!-- Hero placements sit next to the page's own narrative line, which
       already says this in a full sentence — repeating it here was the
       old triple-restatement problem. Compact placements have no
       narrative neighbor, so the descriptor earns its spot. -->
  {#if friendly && !hero}
    <p class="mt-2 text-xs font-medium text-canvas-ink">{friendly}</p>
  {/if}
</div>
