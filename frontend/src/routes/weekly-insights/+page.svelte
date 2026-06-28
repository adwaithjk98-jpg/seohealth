<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';
  import { reduced } from '$lib/motion.js';
  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import { getWeeklyInsightsIndex, getWeeklyInsights } from '$lib/api.js';
  import Skeleton from '$lib/components/Skeleton.svelte';

  /** @type {any} */
  let index = $state(null);
  /** @type {any} */
  let report = $state(null);
  let selectedId = $state(/** @type {number | null} */ (null));
  let loading = $state(true);
  let loadingReport = $state(false);
  let error = $state(/** @type {string | null} */ (null));

  const businesses = $derived(index?.businesses ?? []);
  const isPaid = $derived(report?.tier === 'paid');

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user) {
      await goto('/login', { replaceState: true });
      return;
    }
    try {
      index = await getWeeklyInsightsIndex();
      const rows = index?.businesses ?? [];
      if (rows.length) {
        const wanted = Number($page.url.searchParams.get('business'));
        const match = rows.find((/** @type {any} */ b) => b.business.id === wanted);
        await selectBusiness((match ?? rows[0]).business.id);
      }
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not load your insights.';
    } finally {
      loading = false;
    }
  });

  /** @param {number} businessId */
  async function selectBusiness(businessId) {
    selectedId = businessId;
    loadingReport = true;
    error = null;
    try {
      report = await getWeeklyInsights(businessId);
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not load this report.';
    } finally {
      loadingReport = false;
    }
  }

  /** @param {string | null} iso */
  function fmtDate(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString(undefined, { month: 'long', day: 'numeric' });
    } catch {
      return '';
    }
  }

  const toneText = { positive: 'text-healthy-700', soft: 'text-attention-700', neutral: 'text-canvas-ink' };
  /** @param {number | null | undefined} d */
  function deltaChip(d) {
    if (d == null || d === 0) return null;
    return d > 0 ? `↗ +${d}` : `↘ ${d}`;
  }
  const deltaTone = (/** @type {number} */ d) =>
    d > 0 ? 'bg-healthy-50 text-healthy-700' : 'bg-attention-50 text-attention-700';

  /** Max score across trajectory points, for bar heights. */
  const trajMax = $derived(
    Math.max(100, ...((report?.trajectory?.points ?? []).map((/** @type {any} */ p) => p.score)))
  );

  function leverHref() {
    const l = report?.lever;
    if (!l || !report?.audit_id) return null;
    return `/audits/${report.audit_id}/dashboard/sections/${l.section}?finding=${l.id}`;
  }
</script>

<svelte:head><title>Weekly Insights</title></svelte:head>

<div class="mx-auto max-w-2xl px-4 pb-24 pt-2">
  <a class="btn-ghost -ml-2 text-xs" href="/dashboard">← Back to your businesses</a>

  {#if loading}
    <div class="mt-8 space-y-5" aria-busy="true">
      <Skeleton height="h-8" width="w-40" rounded="full" />
      <Skeleton height="h-24" width="w-full" rounded="2xl" />
      <Skeleton height="h-40" width="w-full" rounded="2xl" />
    </div>
  {:else if error}
    <div class="card mt-8 border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">We couldn't load your insights.</p>
      <p class="mt-1 text-action-700/80">{error}</p>
      <a href="/dashboard" class="btn-ghost mt-3 inline-flex text-xs">Back to dashboard</a>
    </div>
  {:else if !businesses.length}
    <div class="card mt-10 p-8 text-center">
      <p class="text-3xl">🌱</p>
      <h1 class="mt-3 text-xl font-semibold text-canvas-ink">Your first insights are one check away</h1>
      <p class="mt-2 text-sm text-canvas-muted">
        Run a health check on a business and your weekly read starts building here.
      </p>
      <a href="/dashboard" class="btn-primary mt-4 inline-flex">Go to your businesses</a>
    </div>
  {:else}
    <!-- Multi-business switcher (Max). Single-business users never see this. -->
    {#if businesses.length > 1}
      <div class="mt-5 flex flex-wrap gap-2">
        {#each businesses as b (b.business.id)}
          <button
            type="button"
            class={`rounded-full border px-3 py-1.5 text-xs font-medium transition ${
              selectedId === b.business.id
                ? 'border-healthy-300 bg-healthy-50 text-healthy-800'
                : 'border-canvas-soft text-canvas-muted hover:text-canvas-ink'
            }`}
            onclick={() => selectBusiness(b.business.id)}
          >
            {b.business.name}
          </button>
        {/each}
      </div>
    {/if}

    {#if loadingReport}
      <div class="mt-8 space-y-5" aria-busy="true">
        <Skeleton height="h-28" width="w-full" rounded="2xl" />
        <Skeleton height="h-40" width="w-full" rounded="2xl" />
      </div>
    {:else if report}
      <!-- ░░ COVER ░░ -->
      <header class="mt-6" in:fade={reduced({ duration: 300 })}>
        <p class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700">
          <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
          Weekly Insights
        </p>
        <h1 class="mt-4 text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
          {report.cover.business.name}
        </h1>
        <p class="mt-1 text-sm text-canvas-muted">
          {report.cover.business.city} · as of {fmtDate(report.cover.period_end)}
        </p>
      </header>

      <!-- ░░ LEAD — the peak (both tiers) ░░ -->
      <section class="mt-10" in:fly={reduced({ y: 12, duration: 360, easing: quintOut })}>
        <p class={`text-2xl font-semibold leading-tight sm:text-3xl ${toneText[report.lead.tone] ?? 'text-canvas-ink'}`}>
          {report.lead.headline}
        </p>
        <p class="mt-3 text-base text-canvas-muted">{report.lead.sub}</p>
      </section>

      <!-- ░░ TRAJECTORY — the return hook (both tiers) ░░ -->
      {#if report.trajectory?.points?.length > 1}
        <section class="mt-14">
          <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">Your trajectory</p>
          <div class="mt-4 flex items-end gap-2" style="height: 8rem;">
            {#each report.trajectory.points as pt, i}
              <div class="flex flex-1 flex-col items-center justify-end gap-1.5">
                <span class="text-[11px] font-semibold text-canvas-ink">{pt.score}</span>
                <div
                  class={`w-full rounded-t-lg ${i === report.trajectory.points.length - 1 ? 'bg-healthy-500' : 'bg-healthy-200'}`}
                  style={`height: ${Math.max(6, (pt.score / trajMax) * 100)}%;`}
                ></div>
                <span class="text-[10px] text-canvas-muted">{fmtDate(pt.date)}</span>
              </div>
            {/each}
          </div>
          {#if report.trajectory.pillars?.some((/** @type {any} */ p) => p.delta)}
            <ul class="mt-6 space-y-1.5">
              {#each report.trajectory.pillars as p}
                {#if p.delta}
                  <li class="flex items-center justify-between text-sm">
                    <span class="flex items-center gap-2 text-canvas-ink">
                      <span aria-hidden="true">{p.emoji}</span>{p.label}
                    </span>
                    <span class={`rounded-full px-2 py-0.5 text-xs font-medium ${deltaTone(p.delta)}`}>
                      {deltaChip(p.delta)}
                    </span>
                  </li>
                {/if}
              {/each}
            </ul>
          {/if}
        </section>
      {/if}

      {#if isPaid}
        <!-- ░░ GROWTH ░░ -->
        {#if report.growth}
          <section class="mt-14">
            <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">Your reviews</p>
            <p class="mt-3 text-4xl font-semibold tracking-tight text-canvas-ink">
              {report.growth.reviews_now.toLocaleString()}
              {#if report.growth.rating}
                <span class="text-lg font-medium text-canvas-muted">· {report.growth.rating}★</span>
              {/if}
            </p>
            <p class="mt-2 text-sm text-canvas-muted">
              {#if report.growth.reviews_delta > 0}
                <span class="font-medium text-healthy-700">+{report.growth.reviews_delta} this week</span> ·
              {/if}
              {#if report.growth.reviews_total_gained > 0}
                {report.growth.reviews_total_gained} gained since we started watching.
              {:else}
                steady since we started watching.
              {/if}
            </p>
          </section>
        {/if}

        <!-- ░░ STANDING — competitors ░░ -->
        {#if report.standing?.has_competitors}
          <section class="mt-14">
            <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">Where you stand</p>
            <p class={`mt-3 text-lg font-semibold ${toneText[report.standing.tone] ?? 'text-canvas-ink'}`}>
              {report.standing.summary}
            </p>
            <ul class="mt-4 space-y-1">
              {#each report.standing.leaderboard as row, i}
                <li
                  class={`flex items-center justify-between rounded-xl px-3 py-2 text-sm ${
                    row.is_you ? 'bg-healthy-50 font-semibold text-healthy-800' : 'text-canvas-ink'
                  }`}
                >
                  <span class="flex items-center gap-2">
                    <span class="w-5 text-canvas-muted">{i + 1}</span>
                    {row.is_you ? 'You' : row.name}
                  </span>
                  <span class="text-canvas-muted">{row.reviews.toLocaleString()} reviews</span>
                </li>
              {/each}
            </ul>
          </section>
        {/if}

        <!-- ░░ EFFORT — light milestones ░░ -->
        {#if report.effort}
          <section class="mt-14">
            <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">Your progress</p>
            <div class="mt-4 grid grid-cols-3 gap-3">
              <div class="rounded-2xl bg-canvas-soft px-3 py-4 text-center">
                <p class="text-2xl font-semibold text-canvas-ink">{report.effort.fixes_shipped}</p>
                <p class="mt-1 text-[11px] text-canvas-muted">fixes shipped</p>
              </div>
              <div class="rounded-2xl bg-canvas-soft px-3 py-4 text-center">
                <p class="text-2xl font-semibold text-canvas-ink">{report.effort.weeks_monitored}</p>
                <p class="mt-1 text-[11px] text-canvas-muted">weeks watched</p>
              </div>
              <div class="rounded-2xl bg-canvas-soft px-3 py-4 text-center">
                <p class="text-2xl font-semibold text-canvas-ink">{report.effort.checkins}</p>
                <p class="mt-1 text-[11px] text-canvas-muted">check-ins</p>
              </div>
            </div>
            {#if report.effort.fixes_confirmed_period > 0}
              <p class="mt-3 text-sm text-healthy-700">
                ✓ {report.effort.fixes_confirmed_period} of your fixes landed live this week — nice work.
              </p>
            {/if}
          </section>
        {/if}

        <!-- ░░ LEVER — the one move ░░ -->
        {#if report.lever}
          <section class="mt-14">
            <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">Your one move this week</p>
            <a
              href={leverHref()}
              class="card mt-3 block border border-canvas-soft p-5 transition hover:border-healthy-200 hover:shadow-sm"
            >
              <p class="text-xs font-medium text-canvas-muted">{report.lever.section_label}
                {#if report.lever.estimated_time}· {report.lever.estimated_time}{/if}</p>
              <p class="mt-1.5 text-base font-medium text-canvas-ink">{report.lever.title}</p>
              <p class="mt-2 text-sm text-healthy-700">Open this fix →</p>
            </a>
          </section>
        {/if}
      {:else}
        <!-- ░░ FREE WALL ░░ -->
        <section class="mt-14">
          <div class="rounded-3xl bg-gradient-to-br from-healthy-50 to-white p-6 sm:p-8">
            <p class="text-sm font-semibold text-canvas-ink">
              {report.locked.count} more insights in your full report
            </p>
            <ul class="mt-4 space-y-2">
              {#each report.locked.sections as item}
                <li class="flex items-center gap-3 rounded-xl border border-dashed border-healthy-200/70 bg-white/50 px-3 py-2.5 text-sm text-canvas-muted">
                  <span aria-hidden="true">🔒</span>{item}
                </li>
              {/each}
            </ul>
            <p class="mt-5 text-sm text-canvas-muted">
              You're seeing your trend and this week's headline. Pro tells the rest — your review
              growth, how you compare, and the one move that matters — fresh every week.
            </p>
            <a href="/billing" class="btn-primary mt-4 inline-flex">Unlock Weekly Insights →</a>
          </div>
        </section>
      {/if}

      <!-- ░░ PRIDE — the closer (both) ░░ -->
      <section class="mt-16 border-t border-canvas-soft pt-8 text-center">
        <p class="text-sm text-canvas-muted">
          We've kept an eye on <span class="font-medium text-canvas-ink">{report.cover.business.name}</span>
          for <span class="font-medium text-canvas-ink">{report.pride.days_watching} days</span>
          {#if report.pride.checkins > 1}
            · {report.pride.checkins} check-ins
          {/if}.
        </p>
        <p class="mt-1 text-xs text-canvas-muted">Quietly, in the background. That's the whole idea.</p>
      </section>
    {/if}
  {/if}
</div>
