<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import { getLatestAuditForBusiness, startAudit, archiveBusiness } from '$lib/api.js';
  import {
    scoreEncouragement,
    severityLabel,
    severityTone,
    topOpenRecommendations,
    formatRelativeTime
  } from '$lib/dashboard.js';
  import ScoreGauge from '$lib/components/ScoreGauge.svelte';
  import SectionCard from '$lib/components/SectionCard.svelte';
  import CompetitorsSection from '$lib/components/CompetitorsSection.svelte';
  import Skeleton from '$lib/components/Skeleton.svelte';

  // /businesses/{id} is the canonical, audit-id-independent dashboard URL
  // (m6/s5). Bookmarks here survive every re-audit — they always resolve
  // to the latest completed snapshot for this business. Drill-down links
  // still use /audits/{id}/dashboard/sections/{section} for now since
  // those are per-snapshot views.
  const businessId = $derived(parseInt($page.params.id ?? '', 10));

  let audit = $state(/** @type {any} */ (null));
  let status = $state(/** @type {'loading' | 'ready' | 'no_audit' | 'error'} */ ('loading'));
  let errorMessage = $state(/** @type {string | null} */ (null));
  let reauditing = $state(false);
  let reauditError = $state(/** @type {string | null} */ (null));

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user) {
      await goto('/login', { replaceState: true });
      return;
    }

    try {
      audit = await getLatestAuditForBusiness(businessId);
      status = 'ready';
    } catch (err) {
      // 404 here is both "no completed audit yet" and "business not yours"
      // — we render the same affordance for the user-visible case.
      if (err?.status === 404) {
        status = 'no_audit';
        return;
      }
      status = 'error';
      errorMessage = err instanceof Error ? err.message : 'Could not load this business.';
    }
  });

  const sections = $derived(audit?.sections ?? []);
  const top3 = $derived(topOpenRecommendations(sections, 3));
  const totalOpen = $derived(audit?.open_recommendations_count ?? 0);
  const totalDone = $derived(audit?.done_recommendations_count ?? 0);
  const auditId = $derived(audit?.audit_id ?? null);

  // Competitors section (Phase 4) reads the user's plan to switch between
  // upsell-for-free and the real form for paid. Mirrors the gate used on
  // /dashboard for the auto-audit banner.
  const subState = $derived(authState.user?.subscription_state ?? null);
  const tier = $derived(subState?.tier ?? authState.user?.plan ?? 'free');
  const competitorLimit = $derived(subState?.limits?.competitors ?? 0);

  let archiving = $state(false);
  let archiveError = $state(/** @type {string | null} */ (null));
  let confirmingArchive = $state(false);

  async function handleArchive() {
    if (!audit?.business?.id || archiving) return;
    archiving = true;
    archiveError = null;
    try {
      await archiveBusiness(audit.business.id);
      await goto('/dashboard', { replaceState: true });
    } catch (err) {
      archiveError = err instanceof Error ? err.message : 'Could not archive this business.';
      archiving = false;
    }
  }

  /** Same one-shot archive flow but for the empty-state ``no_audit`` page,
   *  where ``audit`` is null so we read the id off the route directly. */
  async function handleArchiveById(id) {
    if (!id || archiving) return;
    archiving = true;
    archiveError = null;
    try {
      await archiveBusiness(id);
      await goto('/dashboard', { replaceState: true });
    } catch (err) {
      archiveError = err instanceof Error ? err.message : 'Could not archive this business.';
      archiving = false;
    }
  }

  async function handleReaudit() {
    if (!audit?.business?.id || reauditing) return;
    reauditing = true;
    reauditError = null;
    try {
      const next = await startAudit(audit.business.id);
      await goto(`/audits/${next.audit_id}`);
    } catch (err) {
      // 409 — an audit is already running for this business (M4/m10).
      // Don't dead-end; route them onto the in-flight live screen.
      if (err instanceof Error) {
        const match = err.message.match(/running_audit_id["\s:]+(\d+)/);
        if (match) {
          await goto(`/audits/${match[1]}`);
          return;
        }
      }
      reauditError = err instanceof Error ? err.message : 'Could not kick off a fresh audit.';
      reauditing = false;
    }
  }

  const severityToneClasses = {
    healthy: 'bg-healthy-50 text-healthy-700',
    attention: 'bg-attention-50 text-attention-700',
    action: 'bg-action-50 text-action-700',
    muted: 'bg-canvas-soft text-canvas-muted'
  };

  function findingHref(rec) {
    return `/audits/${auditId}/dashboard/sections/${rec.section}?finding=${rec.id}`;
  }
</script>

{#if status === 'loading'}
  <section class="space-y-10" aria-busy="true" aria-live="polite">
    <span class="sr-only">Loading your latest health check…</span>
    <header class="flex flex-col items-start justify-between gap-6 lg:flex-row lg:items-center">
      <div class="w-full max-w-md space-y-3">
        <Skeleton height="h-6" width="w-32" rounded="full" />
        <Skeleton height="h-10" width="w-3/4" rounded="lg" />
        <Skeleton height="h-4" width="w-full" />
        <Skeleton height="h-4" width="w-1/2" />
      </div>
      <Skeleton height="h-44" width="w-44" rounded="full" />
    </header>
    <div>
      <Skeleton height="h-5" width="w-56" />
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        {#each Array(4) as _, i}
          <Skeleton height="h-36" width="w-full" rounded="2xl" />
        {/each}
      </div>
    </div>
    <div>
      <Skeleton height="h-5" width="w-64" />
      <div class="mt-4 space-y-3">
        {#each Array(3) as _, i}
          <Skeleton height="h-20" width="w-full" rounded="2xl" />
        {/each}
      </div>
    </div>
  </section>
{:else if status === 'no_audit'}
  <section class="mx-auto mt-10 max-w-md text-center" in:fade={{ duration: 240 }}>
    <div class="card p-6 sm:p-8">
      <p class="text-3xl">🪴</p>
      <h1 class="mt-3 text-lg font-semibold text-canvas-ink">No health check yet</h1>
      <p class="mt-2 text-sm text-canvas-muted">
        We haven't run a check for this business yet. Kick one off from the home page —
        it usually takes about 5 minutes and we'll walk you through every step.
      </p>
      <div class="mt-5 flex flex-col gap-2 sm:flex-row sm:justify-center">
        <a class="btn-primary" href="/">Run a health check</a>
        <a class="btn-ghost" href="/dashboard">Back to dashboard</a>
      </div>
      <button
        type="button"
        class="mt-4 text-xs text-canvas-muted hover:text-action-700"
        onclick={() => handleArchiveById(businessId)}
        disabled={archiving}
      >
        {archiving ? 'Archiving…' : 'Archive this business instead'}
      </button>
      {#if archiveError}
        <p class="mt-3 text-xs text-action-700">{archiveError}</p>
      {/if}
    </div>
  </section>
{:else if status === 'error'}
  <section class="mx-auto mt-10 max-w-2xl text-center" in:fade={{ duration: 240 }}>
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="text-2xl">🌧️</p>
      <p class="mt-2 font-medium">We couldn't load this business right now.</p>
      <p class="mt-1 text-action-700/80">
        {errorMessage ?? 'Give it a moment and try again — your data is still safe.'}
      </p>
      <div class="mt-4 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          class="btn-primary"
          onclick={() => location.reload()}
        >
          ↻ Try again
        </button>
        <a href="/dashboard" class="btn-ghost text-action-700">
          ← Back to your businesses
        </a>
      </div>
    </div>
  </section>
{:else if audit}
  <section class="space-y-10">
    <header class="flex flex-col items-start justify-between gap-6 lg:flex-row lg:items-center">
      <div>
        <p
          class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
          Today’s health check
        </p>
        <h1 class="mt-3 text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
          Hello, {audit.business?.name || 'there'} 👋
        </h1>
        <p class="mt-2 max-w-xl text-sm text-canvas-muted">
          {scoreEncouragement(audit.overall_score)}
        </p>
        <p class="mt-3 text-xs text-canvas-muted">
          Last checked {formatRelativeTime(audit.finished_at)}
          {#if audit.business?.city}· {audit.business.city}{/if}
        </p>
      </div>

      <div in:fade={{ duration: 350 }}>
        <ScoreGauge
          score={audit.overall_score}
          grade={audit.overall_grade}
          label="Overall health"
          trend={audit.overall_trend}
          previousScore={audit.previous_overall_score}
        />
      </div>
    </header>

    <section>
      <div class="flex items-end justify-between gap-3">
        <h2 class="text-lg font-semibold text-canvas-ink">Your four health pillars</h2>
        <p class="text-xs text-canvas-muted">Tap any card to dive in</p>
      </div>
      <div class="mt-4 grid gap-4 sm:grid-cols-2">
        {#each sections as section, i (section.section)}
          <div in:fly={{ y: 12, delay: 80 * i, duration: 320, easing: quintOut }}>
            <SectionCard
              {section}
              href={`/audits/${auditId}/dashboard/sections/${section.section}`}
            />
          </div>
        {/each}
      </div>
    </section>

    {#if top3.length > 0}
      <section in:fade={{ duration: 320, delay: 120 }}>
        <div class="flex items-end justify-between gap-3">
          <h2 class="text-lg font-semibold text-canvas-ink">Top 3 things to do this week</h2>
          {#if totalDone > 0}
            <p class="text-xs text-canvas-muted">
              {totalDone} done · {totalOpen} to go
            </p>
          {/if}
        </div>
        <ol class="mt-4 space-y-3">
          {#each top3 as rec, idx (rec.id)}
            <li>
              <a
                href={findingHref(rec)}
                class="card flex items-start gap-4 p-5 transition hover:border-canvas-muted/30 hover:shadow-soft"
              >
                <span
                  class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-canvas-soft text-sm font-semibold text-canvas-ink"
                  aria-hidden="true"
                >
                  {idx + 1}
                </span>
                <div class="min-w-0 flex-1">
                  <div class="flex flex-wrap items-center gap-2">
                    <span
                      class={`rounded-full px-2 py-0.5 text-xs font-medium ${severityToneClasses[severityTone(rec.severity)]}`}
                    >
                      {severityLabel(rec.severity)}
                    </span>
                    <span class="text-xs text-canvas-muted">
                      {rec.sectionEmoji} {rec.sectionLabel}
                    </span>
                    {#if rec.estimated_time}
                      <span class="text-xs text-canvas-muted">· {rec.estimated_time}</span>
                    {/if}
                  </div>
                  <p class="mt-1 font-medium text-canvas-ink">{rec.title}</p>
                </div>
                <span class="self-center text-canvas-muted">→</span>
              </a>
            </li>
          {/each}
        </ol>
      </section>
    {:else}
      <section
        class="card border border-healthy-100 bg-healthy-50/60 p-6 text-center"
        in:fade={{ duration: 320 }}
      >
        <p class="text-2xl">🎉</p>
        <p class="mt-2 font-medium text-healthy-700">You're all caught up.</p>
        <p class="mt-1 text-sm text-canvas-muted">
          No open recommendations right now. We'll quietly keep checking and let you know when
          something needs attention.
        </p>
      </section>
    {/if}

    {#if audit.business?.id}
      <CompetitorsSection
        businessId={audit.business.id}
        businessName={audit.business?.name || 'Your business'}
        {tier}
        {competitorLimit}
      />
    {/if}

    <footer
      class="card flex flex-col gap-4 border border-canvas-soft bg-canvas-soft/30 p-5 sm:flex-row sm:items-center sm:justify-between"
    >
      <div>
        <p class="text-sm font-medium text-canvas-ink">Want a fresh check?</p>
        <p class="text-xs text-canvas-muted">
          We'll re-run all four pillars and carry your "done" check-marks forward.
        </p>
        {#if reauditError}
          <p
            class="mt-2 rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700"
            in:fade={{ duration: 180 }}
            role="alert"
          >
            {reauditError}
          </p>
        {/if}
      </div>
      <div class="flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-center">
        <a class="btn-ghost w-full sm:w-auto" href="/dashboard">All businesses</a>
        <button
          type="button"
          class="btn-primary w-full sm:w-auto"
          onclick={handleReaudit}
          disabled={reauditing}
        >
          {#if reauditing}
            <span class="inline-flex items-center gap-2">
              <span
                class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                aria-hidden="true"
              ></span>
              Starting…
            </span>
          {:else}
            ↻ Re-audit now
          {/if}
        </button>
        {#if confirmingArchive}
          <div
            class="flex flex-wrap items-center gap-2 text-xs"
            in:fly={{ y: 4, duration: 180, easing: quintOut }}
          >
            <span class="text-canvas-muted">Archive this business?</span>
            <button
              type="button"
              class="rounded-full bg-action-100 px-3 py-1 font-medium text-action-700 hover:bg-action-200"
              onclick={handleArchive}
              disabled={archiving}
            >
              {archiving ? 'Archiving…' : 'Yes, archive'}
            </button>
            <button
              type="button"
              class="rounded-full px-3 py-1 text-canvas-muted hover:text-canvas-ink"
              onclick={() => (confirmingArchive = false)}
              disabled={archiving}
            >
              Cancel
            </button>
          </div>
        {:else}
          <button
            type="button"
            class="text-xs text-canvas-muted hover:text-action-700 sm:ml-auto"
            onclick={() => (confirmingArchive = true)}
          >
            Archive this business
          </button>
        {/if}
      </div>
      {#if archiveError}
        <p
          class="mt-3 rounded-2xl border border-action-100 bg-action-50/80 px-3 py-2 text-xs text-action-700"
          in:fly={{ y: 4, duration: 220, easing: quintOut }}
          role="alert"
        >
          {archiveError}
        </p>
      {/if}
    </footer>
  </section>
{/if}
