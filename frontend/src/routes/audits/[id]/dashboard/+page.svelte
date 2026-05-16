<script>
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { getAudit, startAudit } from '$lib/api.js';
  import {
    scoreEncouragement,
    severityLabel,
    severityTone,
    topOpenRecommendations,
    formatRelativeTime
  } from '$lib/dashboard.js';
  import ScoreGauge from '$lib/components/ScoreGauge.svelte';
  import SectionCard from '$lib/components/SectionCard.svelte';

  const auditId = $derived(parseInt($page.params.id, 10));

  let audit = $state(null);
  let loading = $state(true);
  let errorMessage = $state(/** @type {string | null} */ (null));
  let reauditing = $state(false);
  let reauditError = $state(/** @type {string | null} */ (null));

  onMount(async () => {
    try {
      audit = await getAudit(auditId);
    } catch (err) {
      errorMessage = err instanceof Error ? err.message : 'Could not load your dashboard.';
    } finally {
      loading = false;
    }
  });

  const sections = $derived(audit?.sections ?? []);
  const top3 = $derived(topOpenRecommendations(sections, 3));
  const totalOpen = $derived(audit?.open_recommendations_count ?? 0);
  const totalDone = $derived(audit?.done_recommendations_count ?? 0);

  async function handleReaudit() {
    if (!audit?.business?.id || reauditing) return;
    reauditing = true;
    reauditError = null;
    try {
      const next = await startAudit(audit.business.id);
      await goto(`/audits/${next.audit_id}`);
    } catch (err) {
      // 409 — an audit is already running for this business (M4/m10).
      // Bounce them onto the in-flight live screen rather than dead-ending.
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

{#if loading}
  <section class="mx-auto mt-10 max-w-2xl text-center">
    <p class="text-sm text-canvas-muted">Pulling up your latest audit…</p>
  </section>
{:else if errorMessage}
  <section class="mx-auto mt-10 max-w-2xl text-center">
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">We couldn't load your dashboard.</p>
      <p class="mt-1">{errorMessage}</p>
      <a href="/" class="btn-ghost mt-3 inline-flex text-action-700">← Back home</a>
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

    <footer
      class="card flex flex-col gap-4 border border-canvas-soft bg-canvas-soft/30 p-5 sm:flex-row sm:items-center sm:justify-between"
    >
      <div>
        <p class="text-sm font-medium text-canvas-ink">Want a fresh check?</p>
        <p class="text-xs text-canvas-muted">
          We'll re-run all four pillars and carry your "done" check-marks forward.
        </p>
        {#if reauditError}
          <p class="mt-2 rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700">
            {reauditError}
          </p>
        {/if}
      </div>
      <div class="flex flex-wrap items-center gap-2">
        <a class="btn-ghost" href="/dashboard">All businesses</a>
        <button
          type="button"
          class="btn-primary"
          onclick={handleReaudit}
          disabled={reauditing}
        >
          {#if reauditing}Starting…{:else}↻ Re-audit now{/if}
        </button>
      </div>
    </footer>
  </section>
{/if}
