<script>
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';
  import { defaultPhase } from '$lib/audit-phases.js';

  const auditId = $derived(parseInt($page.params.id, 10));

  let phases = $state([]);
  let business = $state(null);
  let overallScore = $state(null);
  let isComplete = $state(false);
  let errorMessage = $state(null);

  /** @type {EventSource | null} */
  let source = null;

  function ensurePhase(section) {
    if (phases.find((p) => p.section === section)) return;
    phases = [...phases, { ...defaultPhase(section), state: 'pending' }];
  }

  function updatePhase(section, patch) {
    phases = phases.map((p) => (p.section === section ? { ...p, ...patch } : p));
  }

  function handleAuditStarted(event) {
    const data = JSON.parse(event.data);
    business = data.business ?? null;
    phases = (data.sections ?? []).map((s) => ({ ...defaultPhase(s), state: 'pending' }));
  }

  function handleSectionStarted(event) {
    const data = JSON.parse(event.data);
    ensurePhase(data.section);
    updatePhase(data.section, { state: 'running' });
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
      error: data.error ?? null
    });
  }

  function handleAuditCompleted(event) {
    const data = JSON.parse(event.data);
    overallScore = data.overall_score ?? null;
    isComplete = true;
    closeStream();
  }

  function handleAuditFailed(event) {
    const data = JSON.parse(event.data);
    errorMessage = data.error || 'Something went wrong while running your audit.';
    closeStream();
  }

  function closeStream() {
    if (source) {
      source.close();
      source = null;
    }
  }

  onMount(() => {
    if (Number.isNaN(auditId)) {
      errorMessage = 'Audit not found.';
      return;
    }

    source = new EventSource(`/api/audits/${auditId}/stream`);
    source.addEventListener('audit_started', handleAuditStarted);
    source.addEventListener('section_started', handleSectionStarted);
    source.addEventListener('section_completed', handleSectionCompleted);
    source.addEventListener('audit_completed', handleAuditCompleted);
    source.addEventListener('audit_failed', handleAuditFailed);
    // Note: backend buffers events, so a delayed connection still replays from the start.
  });

  onDestroy(closeStream);

  function viewDashboard() {
    goto(`/audits/${auditId}/dashboard`);
  }

  function scoreLabel(score) {
    if (score == null) return '';
    if (score >= 80) return 'Looking good';
    if (score >= 60) return 'A few wins waiting';
    return 'Some attention needed';
  }
</script>

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
    <h1 class="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">
      {#if business}
        Quietly checking on
        <span class="text-healthy-600">{business.name}</span>
      {:else}
        Getting your audit ready…
      {/if}
    </h1>
    {#if business?.city}
      <p class="mt-1 text-sm text-canvas-muted">{business.city}</p>
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

          {#if phase.state === 'done'}
            <div class="mt-1.5 space-y-0.5 text-sm text-canvas-muted" in:fade={{ duration: 250 }}>
              {#if phase.summary}
                <p>{phase.summary}</p>
              {/if}
              {#if phase.score != null}
                <p class="text-canvas-ink">
                  Score <span class="font-medium">{phase.score}</span>/100
                  {#if scoreLabel(phase.score)}
                    <span class="text-canvas-muted">— {scoreLabel(phase.score)}</span>
                  {/if}
                </p>
              {/if}
              {#if phase.recCount > 0}
                <p class="text-xs text-canvas-muted">
                  {phase.recCount} small thing{phase.recCount === 1 ? '' : 's'} to look at
                </p>
              {/if}
            </div>
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
      <p class="font-medium">We couldn't finish this one.</p>
      <p class="mt-1 text-action-700/80">{errorMessage}</p>
      <a class="btn-ghost mt-3 px-0 text-action-700" href="/">Try again →</a>
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
    <p class="mt-10 text-center text-sm text-canvas-muted">
      Connecting to your audit stream…
    </p>
  {/if}
</section>
