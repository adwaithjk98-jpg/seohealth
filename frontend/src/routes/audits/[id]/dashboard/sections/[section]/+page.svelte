<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { afterNavigate, goto } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { getAudit } from '$lib/api.js';
  import {
    severityLabel,
    severityTone,
    statusToTone,
    statusGlyph,
    severityRank,
    scoreLabel
  } from '$lib/dashboard.js';
  import ScoreGauge from '$lib/components/ScoreGauge.svelte';
  import FindingModal from '$lib/components/FindingModal.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  const auditId = $derived(parseInt($page.params.id, 10));
  const sectionKey = $derived($page.params.section);

  let audit = $state(null);
  let loading = $state(true);
  let errorMessage = $state(/** @type {string | null} */ (null));

  onMount(async () => {
    try {
      audit = await getAudit(auditId);
    } catch (err) {
      errorMessage = err instanceof Error ? err.message : 'Could not load this section.';
    } finally {
      loading = false;
    }
  });

  const section = $derived(
    audit?.sections?.find((s) => s.section === sectionKey) ?? null
  );

  // Sort findings by severity for "by impact".
  const findingsByImpact = $derived(
    [...(section?.recommendations ?? [])].sort(
      (a, b) => severityRank(a.severity) - severityRank(b.severity) || a.id - b.id
    )
  );

  const openFindings = $derived(
    findingsByImpact.filter((f) => f.fix_status !== 'done')
  );
  const doneFindings = $derived(
    findingsByImpact.filter((f) => f.fix_status === 'done')
  );

  // Modal state — driven by ?finding=<id> in the URL, so it's bookmarkable.
  const findingIdRaw = $derived($page.url.searchParams.get('finding'));
  const findingId = $derived(findingIdRaw ? parseInt(findingIdRaw, 10) : null);
  const activeFinding = $derived(
    findingId != null
      ? section?.recommendations?.find((r) => r.id === findingId) ?? null
      : null
  );

  function openFinding(rec) {
    const url = new URL($page.url);
    url.searchParams.set('finding', String(rec.id));
    goto(url, { keepFocus: true, noScroll: true });
  }

  // "Back" / closing a finding should return to wherever the user came from —
  // this page is reached from the insights list, a business detail page, AND
  // the audit dashboard, so a hardcoded /dashboard link (or just stripping the
  // ?finding param) stranded people on the wrong page. afterNavigate tells us
  // if there's an in-app history entry to pop; otherwise (a fresh load or deep
  // link) we fall back to the dashboard / stripping the param.
  let cameFromApp = $state(false);
  afterNavigate(({ from }) => {
    if (from) cameFromApp = true;
  });
  const backLabel = $derived(cameFromApp ? 'Back' : 'Back to dashboard');

  function goBack() {
    if (cameFromApp) history.back();
    else goto('/dashboard');
  }

  function closeFinding() {
    // The finding modal is a history entry (opening pushed ?finding, or the
    // insights/business link landed here with it). Closing pops that entry so
    // the user returns to their origin — not the bare section page they never
    // asked to see. Deep-link fallback: strip the param in place.
    if (cameFromApp) {
      history.back();
    } else {
      const url = new URL($page.url);
      url.searchParams.delete('finding');
      goto(url, { keepFocus: true, noScroll: true, replaceState: true });
    }
  }

  function applyUpdatedRec(updated) {
    if (!audit) return;
    audit = {
      ...audit,
      sections: audit.sections.map((sec) => {
        if (sec.section !== updated.section) return sec;
        return {
          ...sec,
          recommendations: sec.recommendations.map((r) =>
            r.id === updated.id ? { ...r, ...updated } : r
          )
        };
      })
    };
    // Update the running open/done counts so Layer 1 reflects the change too.
    const allRecs = audit.sections.flatMap((s) => s.recommendations);
    audit.open_recommendations_count = allRecs.filter((r) => r.fix_status === 'open').length;
    audit.done_recommendations_count = allRecs.filter((r) => r.fix_status === 'done').length;
  }

  const severityToneClasses = {
    healthy: 'bg-healthy-50 text-healthy-700',
    attention: 'bg-attention-50 text-attention-700',
    action: 'bg-action-50 text-action-700',
    muted: 'bg-canvas-soft text-canvas-muted'
  };

  const subCheckToneClasses = {
    healthy: 'bg-healthy-50 text-healthy-700 border-healthy-100',
    attention: 'bg-attention-50 text-attention-700 border-attention-100',
    action: 'bg-action-50 text-action-700 border-action-100',
    muted: 'bg-canvas-soft text-canvas-muted border-canvas-soft'
  };

  // m9 — color the sub-check glyph so ✓ / ! / × actually triage at a glance
  // instead of all reading as monochrome. Matches §2's traffic-light principle.
  const subCheckGlyphClasses = {
    healthy: 'bg-healthy-500 text-white',
    attention: 'bg-attention-500 text-white',
    action: 'bg-action-500 text-white',
    muted: 'bg-white text-canvas-muted'
  };
</script>

<svelte:head>
  <title>{section?.label ?? 'Section'} · SEO Health</title>
</svelte:head>

{#if loading}
  <section class="space-y-8" aria-busy="true" aria-live="polite">
    <span class="sr-only">Loading this section…</span>
    <Skeleton height="h-4" width="w-32" />
    <header class="flex flex-col items-start justify-between gap-6 lg:flex-row lg:items-center">
      <div class="flex w-full max-w-md items-start gap-4">
        <Skeleton height="h-14" width="w-14" rounded="2xl" />
        <div class="flex-1 space-y-2">
          <Skeleton height="h-3" width="w-24" />
          <Skeleton height="h-9" width="w-3/4" rounded="lg" />
          <Skeleton height="h-4" width="w-full" />
        </div>
      </div>
      <Skeleton height="h-40" width="w-40" rounded="full" />
    </header>
    <div>
      <Skeleton height="h-5" width="w-48" />
      <div class="mt-4 grid gap-3 sm:grid-cols-2">
        {#each Array(4) as _, i}
          <Skeleton height="h-20" width="w-full" rounded="2xl" />
        {/each}
      </div>
    </div>
    <div>
      <Skeleton height="h-5" width="w-56" />
      <div class="mt-4 space-y-3">
        {#each Array(3) as _, i}
          <Skeleton height="h-20" width="w-full" rounded="2xl" />
        {/each}
      </div>
    </div>
  </section>
{:else if errorMessage}
  <section class="mx-auto mt-10 max-w-2xl text-center" in:fade={{ duration: 240 }}>
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="text-2xl">🌧️</p>
      <p class="mt-2 font-medium">We couldn't load this section right now.</p>
      <p class="mt-1 text-action-700/80">
        {errorMessage ?? 'Give it a moment and try again.'}
      </p>
      <div class="mt-4 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          class="btn-primary"
          onclick={() => location.reload()}
        >
          ↻ Try again
        </button>
        <button type="button" class="btn-ghost text-action-700" onclick={goBack}>
          ← {backLabel}
        </button>
      </div>
    </div>
  </section>
{:else if !section}
  <section class="mx-auto mt-10 max-w-md text-center" in:fade={{ duration: 240 }}>
    <div class="card p-6 sm:p-8">
      <p class="text-3xl">🪴</p>
      <p class="mt-3 text-base font-medium text-canvas-ink">No data for this section yet</p>
      <p class="mt-1 text-sm text-canvas-muted">
        It may not have been part of your most recent health check.
      </p>
      <button type="button" class="btn-primary mt-4 inline-flex" onclick={goBack}>
        ← {backLabel}
      </button>
    </div>
  </section>
{:else}
  <section class="space-y-8">
    <button
      type="button"
      onclick={goBack}
      class="inline-flex items-center gap-1 text-sm text-canvas-muted hover:text-canvas-ink"
    >
      ← {backLabel}
    </button>

    <header class="flex flex-col items-start justify-between gap-6 lg:flex-row lg:items-center">
      <div class="flex items-start gap-4">
        <span
          class="grid h-14 w-14 shrink-0 place-items-center rounded-2xl bg-canvas-soft text-2xl"
          aria-hidden="true"
        >
          {section.emoji}
        </span>
        <div>
          <p class="text-xs uppercase tracking-wide text-canvas-muted">{section.tagline}</p>
          <h1 class="mt-1 text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
            {section.label}
          </h1>
          {#if section.summary}
            <p class="mt-2 text-sm text-canvas-muted">{section.summary}</p>
          {/if}
        </div>
      </div>

      <div in:fade={{ duration: 320 }}>
        <ScoreGauge
          score={section.score}
          grade={section.grade}
          size={170}
          label="Section score"
          trend={section.trend}
          previousScore={section.previous_score}
        />
      </div>
    </header>

    <section>
      <h2 class="text-lg font-semibold text-canvas-ink">What we checked</h2>
      <p class="text-xs text-canvas-muted">A quick glance at each pillar of this section</p>

      {#if section.sub_checks.length === 0}
        <p class="mt-4 text-sm text-canvas-muted">
          No sub-checks for this section yet.
        </p>
      {:else}
        <ul class="mt-4 grid gap-3 sm:grid-cols-2">
          {#each section.sub_checks as check, i (check.label)}
            <li
              class={`flex items-start gap-3 rounded-2xl border p-4 ${subCheckToneClasses[statusToTone(check.status)]}`}
              in:fly={{ y: 8, delay: 40 * i, duration: 280, easing: quintOut }}
            >
              <span
                class={`grid h-7 w-7 shrink-0 place-items-center rounded-full text-sm font-semibold ${subCheckGlyphClasses[statusToTone(check.status)]}`}
                aria-hidden="true"
              >
                {statusGlyph(check.status)}
              </span>
              <div class="min-w-0">
                <p class="text-sm font-medium text-canvas-ink">{check.label}</p>
                {#if check.value}
                  <p class="text-xs text-canvas-muted">{check.value}</p>
                {/if}
                {#if check.detail}
                  <p class="mt-1 text-xs text-canvas-muted">{check.detail}</p>
                {/if}
              </div>
            </li>
          {/each}
        </ul>
      {/if}
    </section>

    <section>
      <div class="flex items-end justify-between gap-3">
        <h2 class="text-lg font-semibold text-canvas-ink">Findings, sorted by impact</h2>
        {#if doneFindings.length > 0}
          <p class="text-xs text-canvas-muted">
            {doneFindings.length} marked done
          </p>
        {/if}
      </div>

      {#if openFindings.length === 0 && doneFindings.length === 0}
        <p class="mt-4 text-sm text-canvas-muted">
          Nothing flagged here — this pillar is in good shape!
        </p>
      {:else}
        <ol class="mt-4 space-y-3">
          {#each openFindings as rec, i (rec.id)}
            <li in:fly={{ y: 8, delay: 40 * i, duration: 280, easing: quintOut }}>
              <button
                type="button"
                onclick={() => openFinding(rec)}
                class="card flex w-full items-start gap-4 p-5 text-left transition hover:border-canvas-muted/30 hover:shadow-soft"
              >
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <span
                      class={`rounded-full px-2 py-0.5 text-xs font-medium ${severityToneClasses[severityTone(rec.severity)]}`}
                    >
                      {severityLabel(rec.severity)}
                    </span>
                    {#if rec.estimated_time}
                      <span class="text-xs text-canvas-muted">⏱ {rec.estimated_time}</span>
                    {/if}
                  </div>
                  <p class="mt-1 font-medium text-canvas-ink">{rec.title}</p>
                </div>
                <span class="self-center rounded-xl bg-healthy-50 px-3 py-1.5 text-xs font-medium text-healthy-700">
                  Fix it →
                </span>
              </button>
            </li>
          {/each}
        </ol>

        {#if doneFindings.length > 0}
          <details class="mt-6 rounded-2xl border border-canvas-soft bg-canvas-soft/40 p-4 text-sm">
            <summary class="cursor-pointer font-medium text-canvas-ink">
              Things you've already fixed ({doneFindings.length})
            </summary>
            <ul class="mt-3 space-y-2">
              {#each doneFindings as rec (rec.id)}
                <li>
                  <button
                    type="button"
                    onclick={() => openFinding(rec)}
                    class="flex w-full items-center justify-between gap-3 rounded-xl bg-white px-3 py-2 text-left text-sm hover:bg-canvas-soft"
                  >
                    <span class="text-canvas-ink line-through decoration-canvas-muted/50">
                      {rec.title}
                    </span>
                    <span class="text-xs text-healthy-700">✓ done</span>
                  </button>
                </li>
              {/each}
            </ul>
          </details>
        {/if}
      {/if}
    </section>

    <p class="text-xs text-canvas-muted">
      Tap any finding for the why, the impact, and a step-by-step fix.
    </p>
  </section>

  {#if activeFinding}
    <FindingModal
      recommendation={activeFinding}
      sectionLabel={section.label}
      sectionEmoji={section.emoji}
      onClose={closeFinding}
      onUpdate={applyUpdatedRec}
    />
  {/if}
{/if}
