<script>
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';
  import { defaultPhase, progressCopy } from '$lib/audit-phases.js';
  import { getAudit, startAudit } from '$lib/api.js';
  import { topOpenRecommendations, severityLabel } from '$lib/dashboard.js';

  const auditId = $derived(parseInt($page.params.id, 10));

  let phases = $state([]);
  let business = $state(null);
  let overallScore = $state(null);
  let isComplete = $state(false);
  let errorMessage = $state(null);
  let stalled = $state(false);
  let retrying = $state(false);
  let retryError = $state(/** @type {string | null} */ (null));
  // Audit_started flips this; first-audit vs returning frames the
  // header copy and the per-phase "compared to last time" UI.
  let isFirstAudit = $state(false);
  // Top finding for the first-audit reveal moment. We fetch the audit
  // detail once on completion to surface the single highest-impact rec
  // inline ("the most important thing to look at this week") so the
  // first-audit screen doesn't dead-end at a score.
  let topFinding = $state(/** @type {any} */ (null));

  /** @type {EventSource | null} */
  let source = null;
  /** @type {ReturnType<typeof setTimeout> | null} */
  let stalledTimer = null;
  // Audit jobs cap at ~10min; "taking longer than usual" copy at 90s of
  // no new section_completed event is the sweet spot — long enough to
  // not nag a healthy run, short enough to soften the wait on a slow one.
  const STALLED_AFTER_MS = 90_000;

  function ensurePhase(section) {
    if (phases.find((p) => p.section === section)) return;
    phases = [...phases, { ...defaultPhase(section), state: 'pending' }];
  }

  function updatePhase(section, patch) {
    phases = phases.map((p) => (p.section === section ? { ...p, ...patch } : p));
  }

  function bumpStalledTimer() {
    stalled = false;
    if (stalledTimer) clearTimeout(stalledTimer);
    stalledTimer = setTimeout(() => {
      stalled = true;
    }, STALLED_AFTER_MS);
  }

  function clearStalledTimer() {
    if (stalledTimer) {
      clearTimeout(stalledTimer);
      stalledTimer = null;
    }
    stalled = false;
  }

  function handleAuditStarted(event) {
    const data = JSON.parse(event.data);
    business = data.business ?? null;
    isFirstAudit = Boolean(data.is_first_audit);
    phases = (data.sections ?? []).map((s) => ({ ...defaultPhase(s), state: 'pending' }));
    bumpStalledTimer();
  }

  function handleSectionStarted(event) {
    const data = JSON.parse(event.data);
    ensurePhase(data.section);
    updatePhase(data.section, { state: 'running' });
    bumpStalledTimer();
  }

  function handleSectionProgress(event) {
    const data = JSON.parse(event.data);
    ensurePhase(data.section);
    const copy = progressCopy(data.section, data.step, data.detail);
    if (copy) updatePhase(data.section, { progressLine: copy });
    bumpStalledTimer();
  }

  function handleSectionCompleted(event) {
    const data = JSON.parse(event.data);
    ensurePhase(data.section);
    const phase = defaultPhase(data.section);
    const summary = data.status !== 'failed' ? phase.summarize(data.summary ?? {}) : null;
    updatePhase(data.section, {
      state: data.status === 'failed' ? 'failed' : 'done',
      score: data.score ?? null,
      summary,
      recCount: data.recommendation_count ?? 0,
      error: data.error ?? null,
      // Live-diff payload. ``previousScore`` is the same pillar's
      // score from the prior audit (null on first run);
      // ``highlight`` is the short newsy headline the backend
      // computes from raw_data + previous raw_data.
      previousScore: data.previous_score ?? null,
      highlight: data.highlight ?? null,
      optedOut: Boolean(data.opted_out)
    });
    bumpStalledTimer();
  }

  async function handleAuditCompleted(event) {
    const data = JSON.parse(event.data);
    overallScore = data.overall_score ?? null;
    isComplete = true;
    clearStalledTimer();
    closeStream();
    // First-audit users land here knowing nothing about the dashboard
    // yet — fetch the audit detail to pull the single highest-impact
    // recommendation so the reveal card has something concrete to act
    // on instead of just a score. Returning users skip the fetch.
    if (isFirstAudit) {
      try {
        const detail = await getAudit(auditId);
        const top = topOpenRecommendations(detail.sections ?? [], 1);
        topFinding = top[0] ?? null;
      } catch {
        // Best-effort enrichment — the score + dashboard CTA still
        // works without it.
      }
    }
  }

  function handleAuditFailed(event) {
    const data = JSON.parse(event.data);
    errorMessage = data.error || 'Something went wrong while running your audit.';
    clearStalledTimer();
    closeStream();
  }

  function closeStream() {
    if (source) {
      source.close();
      source = null;
    }
  }

  /**
   * Pre-subscription status probe (B2): a user landing on /audits/{id} for
   * an audit that is *already* done or failed must not be left staring at
   * the live-streaming UI. We hit /api/audits/{id} once; if the audit
   * already terminated, short-circuit (redirect on done, render the
   * recovery surface on failed) and never open the SSE connection.
   */
  async function checkExistingStatus() {
    try {
      const audit = await getAudit(auditId);
      if (audit.status === 'done') {
        // Straight to the canonical business view — /audits/{id}/dashboard
        // is a redirect kept only for old bookmarks.
        const target = audit.business?.id
          ? `/businesses/${audit.business.id}`
          : `/audits/${auditId}/dashboard`;
        await goto(target, { replaceState: true });
        return 'terminal';
      }
      if (audit.status === 'failed') {
        business = audit.business ?? null;
        errorMessage =
          audit.error_message || 'Something went wrong while running your audit.';
        return 'terminal';
      }
      return 'live';
    } catch (err) {
      // 404 / 401 / network — fall through to the SSE attempt; if the
      // audit really doesn't exist, the stream endpoint will surface it.
      return 'live';
    }
  }

  async function handleRetry() {
    if (!business?.id || retrying) return;
    retrying = true;
    retryError = null;
    try {
      const next = await startAudit(business.id);
      await goto(`/audits/${next.audit_id}`, { replaceState: true });
    } catch (err) {
      // 409 = an audit is already running for this business (M4/m10);
      // bounce them onto that one instead of dead-ending.
      if (err instanceof Error) {
        const match = err.message.match(/running_audit_id["\s:]+(\d+)/);
        if (match) {
          await goto(`/audits/${match[1]}`, { replaceState: true });
          return;
        }
      }
      retryError =
        err instanceof Error ? err.message : 'Could not kick off a fresh audit.';
      retrying = false;
    }
  }

  onMount(async () => {
    if (Number.isNaN(auditId)) {
      errorMessage = 'Audit not found.';
      return;
    }

    const state = await checkExistingStatus();
    if (state === 'terminal') return;

    source = new EventSource(`/api/audits/${auditId}/stream`);
    source.addEventListener('audit_started', handleAuditStarted);
    source.addEventListener('section_started', handleSectionStarted);
    source.addEventListener('section_progress', handleSectionProgress);
    source.addEventListener('section_completed', handleSectionCompleted);
    source.addEventListener('audit_completed', handleAuditCompleted);
    source.addEventListener('audit_failed', handleAuditFailed);
    // Note: backend buffers events, so a delayed connection still replays from the start.
    bumpStalledTimer();
  });

  onDestroy(() => {
    closeStream();
    clearStalledTimer();
  });

  function viewDashboard() {
    if (business?.id) {
      goto(`/businesses/${business.id}`);
    } else {
      goto(`/audits/${auditId}/dashboard`);
    }
  }

  function scoreLabel(score) {
    if (score == null) return '';
    if (score >= 80) return 'Looking good';
    if (score >= 60) return 'A few wins waiting';
    return 'Some attention needed';
  }
</script>

<svelte:head><title>Health check · SEO Health</title></svelte:head>

<section class="mx-auto max-w-2xl">
  <header class="text-center">
    <p
      class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
    >
      {#if isComplete}
        <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
        All done
      {:else if errorMessage}
        <span class="h-1.5 w-1.5 rounded-full bg-action-500"></span>
        Hit a snag
      {:else}
        <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-healthy-500"></span>
        Live analysis
      {/if}
    </p>
    <h1 class="mt-3 text-2xl font-semibold tracking-tight sm:text-4xl">
      {#if business && isFirstAudit}
        Getting to know
        <span class="text-healthy-600">{business.name}</span>
      {:else if business}
        Re-checking
        <span class="text-healthy-600">{business.name}</span>
      {:else}
        Getting your audit ready…
      {/if}
    </h1>
    {#if business}
      <p class="mt-1 text-xs text-canvas-muted">
        {#if isFirstAudit}
          First time through — we'll walk you through what we found at the end.
        {:else}
          Watching for anything that changed since last time.
        {/if}
      </p>
    {/if}
    {#if business?.city}
      <p class="mt-1 text-sm text-canvas-muted">{business.city}</p>
    {/if}
    {#if stalled && !errorMessage && !isComplete}
      <p class="mt-3 text-xs text-canvas-muted" in:fade={{ duration: 250 }}>
        Taking a little longer than usual — hang tight, we'll keep you posted.
      </p>
    {/if}
  </header>

  <ol class="mt-10 space-y-3">
    {#each phases as phase (phase.section)}
      <li
        class="card flex items-start gap-4 p-5"
        in:fly={{ y: 12, duration: 350, easing: quintOut }}
      >
        <div
          class="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-canvas-soft text-lg"
          aria-hidden="true"
        >
          {phase.emoji}
        </div>

        <div class="min-w-0 flex-1">
          <div class="flex items-center justify-between gap-3">
            <p class="font-medium text-canvas-ink">
              {phase.state === 'done' || phase.state === 'failed'
                ? phase.label
                : phase.runningCopy}
            </p>
            <div class="flex items-center gap-2 text-xs">
              {#if phase.state === 'pending'}
                <span class="text-canvas-muted">waiting</span>
              {:else if phase.state === 'running'}
                <span
                  class="inline-block h-3 w-3 animate-spin rounded-full border-2 border-healthy-300 border-t-healthy-600"
                  aria-label="running"
                ></span>
              {:else if phase.state === 'done'}
                <span
                  class="inline-flex items-center gap-1 rounded-full bg-healthy-50 px-2 py-0.5 font-medium text-healthy-700"
                  in:fade={{ duration: 250 }}
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    viewBox="0 0 20 20"
                    fill="currentColor"
                    class="h-3.5 w-3.5"
                    aria-hidden="true"
                  >
                    <path
                      fill-rule="evenodd"
                      d="M16.704 5.29a1 1 0 010 1.42l-7.5 7.5a1 1 0 01-1.42 0l-3.5-3.5a1 1 0 011.42-1.42L8.5 12.08l6.79-6.79a1 1 0 011.414 0z"
                      clip-rule="evenodd"
                    />
                  </svg>
                  {phase.completedCopy}
                </span>
              {:else if phase.state === 'failed'}
                <span
                  class="rounded-full bg-action-50 px-2 py-0.5 font-medium text-action-700"
                >
                  Skipped
                </span>
              {/if}
            </div>
          </div>

          {#if phase.state === 'running' && phase.progressLine}
            <p class="mt-1.5 text-sm text-canvas-muted" in:fade={{ duration: 250 }}>
              {phase.progressLine}
            </p>
          {/if}

          {#if phase.state === 'done'}
            <div class="mt-1.5 space-y-1 text-sm text-canvas-muted" in:fade={{ duration: 250 }}>
              {#if phase.highlight}
                <!-- Live-diff headline. Reads as news ("8 new
                     reviews since last check") rather than as a
                     static summary, which is what makes the 5-minute
                     wait feel like something is happening. -->
                <p class="font-medium text-canvas-ink">{phase.highlight}</p>
              {:else if phase.summary}
                <p>{phase.summary}</p>
              {/if}
              {#if phase.score != null && !phase.optedOut}
                <p class="flex flex-wrap items-baseline gap-x-2 text-canvas-ink">
                  <span>
                    Score <span class="font-medium">{phase.score}</span>/100
                  </span>
                  {#if phase.previousScore != null && phase.previousScore !== phase.score}
                    {@const diff = phase.score - phase.previousScore}
                    {@const tone = diff > 0 ? 'text-healthy-700 bg-healthy-50' : 'text-action-700 bg-action-50'}
                    <span class={`rounded-full px-1.5 py-0.5 text-[11px] font-medium ${tone}`}>
                      {diff > 0 ? '↑' : '↓'} {Math.abs(diff)} from {phase.previousScore}
                    </span>
                  {:else if phase.previousScore == null}
                    <span class="text-xs text-canvas-muted">first reading</span>
                  {/if}
                  {#if scoreLabel(phase.score)}
                    <span class="text-canvas-muted text-xs">— {scoreLabel(phase.score)}</span>
                  {/if}
                </p>
              {/if}
              {#if phase.recCount > 0}
                <p class="text-xs text-canvas-muted">
                  {phase.recCount} small thing{phase.recCount === 1 ? '' : 's'} to look at
                </p>
              {/if}
            </div>
          {:else if phase.state === 'failed' && phase.optedOut}
            <p class="mt-1.5 text-sm text-canvas-muted" in:fade={{ duration: 250 }}>
              {phase.highlight ?? "Skipped — you opted out of this pillar."}
            </p>
          {:else if phase.state === 'failed'}
            <p class="mt-1.5 text-sm text-canvas-muted">
              We'll come back to this one — the rest of your audit is still on track.
            </p>
          {/if}
        </div>
      </li>
    {/each}
  </ol>

  {#if errorMessage}
    <div
      class="mt-8 rounded-2xl border border-action-100 bg-action-50 p-5 text-sm text-action-700"
      in:fade={{ duration: 250 }}
    >
      <p class="font-medium">
        Something went wrong while checking on {business?.name ?? 'your business'}.
      </p>
      <p class="mt-1 text-action-700/80">{errorMessage}</p>
      {#if retryError}
        <p class="mt-3 rounded-xl bg-white/60 px-3 py-2 text-xs">{retryError}</p>
      {/if}
      <div class="mt-4 flex flex-col gap-2 sm:flex-row sm:flex-wrap">
        {#if business?.id}
          <button
            type="button"
            class="btn-primary w-full sm:w-auto"
            disabled={retrying}
            onclick={handleRetry}
          >
            {#if retrying}
              <span class="inline-flex items-center justify-center gap-2">
                <span
                  class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                  aria-hidden="true"
                ></span>
                Starting…
              </span>
            {:else}
              ↻ Try again
            {/if}
          </button>
        {/if}
        <a class="btn-ghost w-full text-action-700 sm:w-auto" href="/dashboard">
          Back to your dashboard
        </a>
      </div>
    </div>
  {:else if isComplete && isFirstAudit}
    <!-- First-audit reveal moment. Returning users skip this; they
         know the dashboard. New users get a deliberate three-beat
         orientation — score, what we found, what to fix first — so
         the 5-minute wait pays off in narrative, not just a number. -->
    <div
      class="mt-10 space-y-6"
      in:fly={{ y: 8, duration: 350, easing: quintOut }}
    >
      <div class="card p-6 text-center sm:p-8">
        <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
          Your first health check
        </p>
        {#if overallScore != null}
          <p class="mt-2 text-6xl font-semibold tracking-tight text-healthy-600">
            {overallScore}
          </p>
          <p class="mt-1 text-sm text-canvas-ink">{scoreLabel(overallScore)} · out of 100</p>
        {:else}
          <p class="mt-2 text-base text-canvas-ink">Your personalised plan is ready.</p>
        {/if}
      </div>

      <div class="card p-5 sm:p-6">
        <p class="text-sm font-semibold text-canvas-ink">What we looked at</p>
        <p class="mt-1 text-xs text-canvas-muted">
          The pillars that decide how easy you are to find online. Tap any one on the
          dashboard to dig into the details.
        </p>
        <ul class="mt-3 space-y-1.5 text-sm">
          {#each phases as phase (phase.section)}
            <li class="flex items-center justify-between gap-3">
              <span class="flex items-center gap-2 text-canvas-ink">
                <span aria-hidden="true">{phase.emoji}</span>
                {phase.label}
              </span>
              <span class="text-canvas-muted">
                {#if phase.optedOut}
                  Skipped
                {:else if phase.score != null}
                  {phase.score}/100
                {:else}
                  —
                {/if}
              </span>
            </li>
          {/each}
        </ul>
      </div>

      {#if topFinding}
        <div class="card border border-attention-100 bg-attention-50/60 p-5 sm:p-6">
          <p class="text-xs font-semibold uppercase tracking-wide text-attention-700">
            The single biggest fix this week
          </p>
          <p class="mt-2 text-sm font-semibold text-canvas-ink">{topFinding.title}</p>
          <div class="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-canvas-muted">
            <span>{severityLabel(topFinding.severity)}</span>
            <span>·</span>
            <span>{topFinding.sectionEmoji} {topFinding.sectionLabel}</span>
            {#if topFinding.estimated_time}
              <span>·</span>
              <span>{topFinding.estimated_time}</span>
            {/if}
          </div>
          <p class="mt-3 text-xs text-canvas-muted">
            Don't worry — your dashboard has the step-by-step fix, plus two more small
            things to look at when you have a moment.
          </p>
        </div>
      {/if}

      <button
        type="button"
        class="btn-primary w-full"
        onclick={viewDashboard}
      >
        Take me to my dashboard →
      </button>
    </div>
  {:else if isComplete}
    <div
      class="mt-10 flex flex-col items-center gap-3 text-center"
      in:fly={{ y: 8, duration: 350, easing: quintOut }}
    >
      {#if overallScore != null}
        <p class="text-sm text-canvas-muted">Your overall health</p>
        <p class="text-5xl font-semibold tracking-tight text-healthy-600">{overallScore}</p>
        <p class="text-sm text-canvas-ink">{scoreLabel(overallScore)}</p>
      {:else}
        <p class="text-base text-canvas-ink">Your personalized plan is ready.</p>
      {/if}
      <button type="button" class="btn-primary mt-2" onclick={viewDashboard}>
        Show me my dashboard
      </button>
    </div>
  {:else if phases.length === 0}
    <div class="mt-10 space-y-3" aria-busy="true" aria-live="polite">
      <span class="sr-only">Connecting to your audit stream…</span>
      {#each Array(4) as _, i}
        <div class="card flex items-center gap-4 p-5">
          <div
            class="skeleton h-10 w-10 shrink-0 rounded-xl"
            aria-hidden="true"
          ></div>
          <div class="flex-1 space-y-2">
            <div class="skeleton h-4 w-3/4 rounded-lg" aria-hidden="true"></div>
            <div class="skeleton h-3 w-1/2 rounded-lg" aria-hidden="true"></div>
          </div>
        </div>
      {/each}
      <p class="pt-2 text-center text-xs text-canvas-muted">
        Connecting to your audit stream… first results in just a moment.
      </p>
    </div>
  {/if}
</section>
