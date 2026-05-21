<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fade, fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import { deleteCompetitor } from '$lib/api.js';
  import { formatRelativeTime } from '$lib/dashboard.js';
  import TrendChart from '$lib/components/TrendChart.svelte';

  /**
   * @type {{
   *   data: {
   *     business: any | null,
   *     competitor: any | null,
   *     trends: any | null,
   *     error: string | null
   *   }
   * }}
   */
  let { data } = $props();

  const business = $derived(data?.business ?? null);
  const competitor = $derived(data?.competitor ?? null);
  const trends = $derived(data?.trends ?? null);
  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );

  // 1-on-1 trend: only this competitor's trace on the chart alongside the
  // user's own. Filter the wider trends payload down to one row.
  const oneOnOneTrends = $derived(
    competitor && trends
      ? {
          business: trends.business ?? [],
          competitors: (trends.competitors ?? []).filter(
            (/** @type {any} */ c) => c.competitor_id === competitor.id
          )
        }
      : { business: [], competitors: [] }
  );

  /** @type {'overview' | 'reviews' | 'social'} */
  let tab = $state('overview');
  /** @type {'review_count' | 'rating' | 'instagram_followers' | 'instagram_posts'} */
  let metric = $state('review_count');

  /** Toggle options for the Overview 1-on-1 chart. Mirrors the Market
   * page so the same vocabulary is used across the workspace. */
  const metricOptions = /** @type {const} */ ([
    { key: 'review_count', label: 'Reviews' },
    { key: 'rating', label: 'Rating' },
    { key: 'instagram_followers', label: 'IG followers' },
    { key: 'instagram_posts', label: 'IG posts' }
  ]);

  // Reviews tab: pull this competitor's observation stream and the user's
  // own series, then compute simple deterministic comparisons. No LLM
  // here — the deep dive is a raw read of the data.
  const competitorTrend = $derived(oneOnOneTrends.competitors[0] ?? null);
  const competitorObs = $derived(
    /** @type {any[]} */ (competitorTrend?.observations ?? [])
  );
  const userObs = $derived(/** @type {any[]} */ (oneOnOneTrends.business ?? []));

  /** @param {any[]} series */
  function reviewVelocity(series) {
    const points = series.filter((p) => p.review_count != null);
    if (points.length < 2) return null;
    const first = points[0];
    const last = points[points.length - 1];
    const firstTime = new Date(first.observed_at + 'Z').getTime();
    const lastTime = new Date(last.observed_at + 'Z').getTime();
    const days = (lastTime - firstTime) / (1000 * 60 * 60 * 24);
    if (days <= 0) return null;
    const delta = last.review_count - first.review_count;
    return { delta, days: Math.round(days), perWeek: delta / (days / 7) };
  }

  const userVelocity = $derived(reviewVelocity(userObs));
  const compVelocity = $derived(reviewVelocity(competitorObs));

  let removing = $state(false);
  let removeError = $state(/** @type {string | null} */ (null));
  let confirmingRemove = $state(false);

  async function handleRemove() {
    if (!business || !competitor) return;
    removing = true;
    removeError = null;
    try {
      await deleteCompetitor(business.id, competitor.id);
      await goto('/dashboard/competitors', { replaceState: true });
    } catch (err) {
      removeError = err instanceof Error ? err.message : 'Could not remove this competitor.';
      removing = false;
    }
  }

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user || data?.error === 'unauthenticated') {
      await goto('/login', { replaceState: true });
    }
  });

  const tabs = [
    { key: /** @type {const} */ ('overview'), label: 'Overview' },
    { key: /** @type {const} */ ('reviews'), label: 'Reviews' },
    { key: /** @type {const} */ ('social'), label: 'Social' }
  ];
</script>

<section class="space-y-6">
  <header class="space-y-2">
    <a class="btn-ghost -ml-2 text-xs" href="/dashboard/competitors">← Back to hub</a>
    {#if competitor && business}
      <h1 class="text-2xl font-semibold tracking-tight text-canvas-ink sm:text-3xl">
        {competitor.name}
      </h1>
      <p class="text-sm text-canvas-muted">
        Comparing against <span class="text-canvas-ink">{business.name}</span>
        {#if business.city} · {business.city}{/if}
      </p>
    {/if}
  </header>

  {#if errorMessage}
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">We couldn't load this competitor.</p>
      <p class="mt-1 text-action-700/80">{errorMessage}</p>
      <a class="btn-ghost mt-3 inline-flex text-action-700" href="/dashboard/competitors">
        Back to hub
      </a>
    </div>
  {:else if business && competitor}
    <nav
      class="-mx-4 flex gap-1 overflow-x-auto border-b border-canvas-soft px-4 sm:mx-0 sm:px-0"
      aria-label="Competitor detail sections"
    >
      {#each tabs as t (t.key)}
        {@const active = tab === t.key}
        <button
          type="button"
          class={`relative -mb-px inline-flex min-h-[40px] items-center whitespace-nowrap px-4 py-2 text-sm font-medium transition-colors duration-200 ${
            active ? 'text-canvas-ink' : 'text-canvas-muted hover:text-canvas-ink'
          }`}
          aria-current={active ? 'page' : undefined}
          onclick={() => (tab = t.key)}
        >
          {t.label}
          {#if active}
            <span class="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-healthy-500"></span>
          {/if}
        </button>
      {/each}
    </nav>

    {#if tab === 'overview'}
      <section class="space-y-4" in:fade={{ duration: 200 }}>
        <div class="card p-4 sm:p-5">
          <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div>
              <p class="text-sm font-medium text-canvas-ink">1-on-1 trend</p>
              <p class="text-xs text-canvas-muted">
                {business.name} vs {competitor.name}
              </p>
            </div>
            <div
              class="inline-flex max-w-full items-center gap-1 overflow-x-auto rounded-full bg-canvas-soft p-1 text-xs"
              role="tablist"
              aria-label="Metric"
            >
              {#each metricOptions as opt (opt.key)}
                <button
                  type="button"
                  role="tab"
                  aria-selected={metric === opt.key}
                  class={`min-h-[32px] whitespace-nowrap rounded-full px-3 py-1 font-medium transition-all ${
                    metric === opt.key
                      ? 'bg-white text-canvas-ink shadow-soft'
                      : 'text-canvas-muted hover:text-canvas-ink'
                  }`}
                  onclick={() => (metric = opt.key)}
                >
                  {opt.label}
                </button>
              {/each}
            </div>
          </div>
          <TrendChart
            business={oneOnOneTrends.business}
            competitors={oneOnOneTrends.competitors}
            businessName={business.name}
            {metric}
          />
        </div>

        <div class="grid gap-3 sm:grid-cols-2">
          <div class="card p-4">
            <p class="text-xs uppercase tracking-wide text-canvas-muted">Latest rating</p>
            <p class="mt-1 text-xl font-semibold text-canvas-ink">
              {#if competitor.latest_rating != null}
                {Number(competitor.latest_rating).toFixed(1)} ★
              {:else}
                <span class="text-canvas-muted text-sm font-normal">No reading yet</span>
              {/if}
            </p>
            {#if competitor.latest_observed_at}
              <p class="mt-1 text-xs text-canvas-muted">
                last seen {formatRelativeTime(competitor.latest_observed_at + 'Z')}
              </p>
            {/if}
          </div>
          <div class="card p-4">
            <p class="text-xs uppercase tracking-wide text-canvas-muted">Latest review count</p>
            <p class="mt-1 text-xl font-semibold text-canvas-ink">
              {#if competitor.latest_review_count != null}
                {competitor.latest_review_count}
              {:else}
                <span class="text-canvas-muted text-sm font-normal">No reading yet</span>
              {/if}
            </p>
            <p class="mt-1 text-xs text-canvas-muted">
              {competitor.observation_count}
              {competitor.observation_count === 1 ? 'observation' : 'observations'} on file
            </p>
          </div>
        </div>
      </section>
    {:else if tab === 'reviews'}
      <section class="space-y-4" in:fade={{ duration: 200 }}>
        <div class="card p-5 text-sm text-canvas-muted">
          <p class="text-canvas-ink font-medium">Review volume growth</p>
          <p class="mt-1 text-xs">
            Tracked over the {competitorObs.length}
            {competitorObs.length === 1 ? 'observation' : 'observations'} we have on this
            competitor so far.
          </p>
          <dl class="mt-4 grid gap-3 sm:grid-cols-2">
            <div class="rounded-xl bg-canvas-soft/40 p-3">
              <dt class="text-xs uppercase tracking-wide text-canvas-muted">{business.name}</dt>
              {#if userVelocity}
                <dd class="mt-1 text-sm text-canvas-ink">
                  +{userVelocity.delta} reviews · {userVelocity.perWeek.toFixed(1)}/week
                  <span class="text-canvas-muted">over {userVelocity.days} days</span>
                </dd>
              {:else}
                <dd class="mt-1 text-sm text-canvas-muted">Not enough data yet.</dd>
              {/if}
            </div>
            <div class="rounded-xl bg-canvas-soft/40 p-3">
              <dt class="text-xs uppercase tracking-wide text-canvas-muted">
                {competitor.name}
              </dt>
              {#if compVelocity}
                <dd class="mt-1 text-sm text-canvas-ink">
                  +{compVelocity.delta} reviews · {compVelocity.perWeek.toFixed(1)}/week
                  <span class="text-canvas-muted">over {compVelocity.days} days</span>
                </dd>
              {:else}
                <dd class="mt-1 text-sm text-canvas-muted">Not enough data yet.</dd>
              {/if}
            </div>
          </dl>
        </div>

        <div class="card p-4 sm:p-5">
          <div class="mb-3">
            <p class="text-sm font-medium text-canvas-ink">Review count over time</p>
          </div>
          <TrendChart
            business={oneOnOneTrends.business}
            competitors={oneOnOneTrends.competitors}
            businessName={business.name}
            metric="review_count"
          />
        </div>
      </section>
    {:else if tab === 'social'}
      <section class="space-y-4" in:fade={{ duration: 200 }}>
        <div class="card p-5">
          <p class="text-canvas-ink font-medium">Social signals</p>
          <p class="mt-1 text-xs text-canvas-muted">
            Follower growth and post frequency will populate here once we have a few observations
            from the audit pipeline. We don't pull any image data — only counts.
          </p>
          {#if competitor.instagram_url}
            <p class="mt-3 text-xs text-canvas-muted">
              Tracking from
              <a
                class="text-healthy-700 underline"
                href={competitor.instagram_url}
                target="_blank"
                rel="noopener noreferrer">{competitor.instagram_url}</a
              >
            </p>
          {:else}
            <p class="mt-3 text-xs text-canvas-muted">
              No Instagram URL pre-seeded. The scraper will discover it from the Maps listing on
              the next audit.
            </p>
          {/if}
        </div>
      </section>
    {/if}

    <div class="flex flex-wrap items-center gap-2 pt-2">
      <a class="btn-ghost" href="/dashboard/competitors">← Back to hub</a>
      {#if confirmingRemove}
        <div
          class="ml-auto flex items-center gap-2 text-xs"
          in:fly={{ y: 4, duration: 180, easing: quintOut }}
        >
          <span class="text-canvas-muted">Stop tracking?</span>
          <button
            type="button"
            class="btn-ghost text-xs"
            onclick={() => (confirmingRemove = false)}
            disabled={removing}
          >
            Cancel
          </button>
          <button
            type="button"
            class="inline-flex min-h-[36px] items-center justify-center rounded-xl bg-action-500 px-3 py-1.5 text-xs font-medium text-white shadow-soft transition hover:bg-action-600 disabled:opacity-60"
            onclick={handleRemove}
            disabled={removing}
          >
            {removing ? 'Removing…' : 'Yes, remove'}
          </button>
        </div>
      {:else}
        <button
          type="button"
          class="btn-ghost ml-auto text-xs"
          onclick={() => (confirmingRemove = true)}
        >
          Remove competitor
        </button>
      {/if}
    </div>
    {#if removeError}
      <p class="rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700">{removeError}</p>
    {/if}
  {/if}
</section>
