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
   *     anchorTrends: any | null,
   *     businessTrends: Record<number, any>,
   *     businesses: any[],
   *     error: string | null
   *   }
   * }}
   */
  let { data } = $props();

  const business = $derived(data?.business ?? null);
  const competitor = $derived(data?.competitor ?? null);
  const anchorTrends = $derived(data?.anchorTrends ?? { business: [], competitors: [] });
  const businessTrends = $derived(data?.businessTrends ?? {});
  const businesses = $derived(data?.businesses ?? []);
  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );

  // This competitor's observation series, pulled from the anchor business's
  // /trends payload (which is where the backend persists competitor obs).
  const competitorSeries = $derived(
    competitor
      ? (anchorTrends.competitors ?? []).find(
          (/** @type {any} */ c) => c.competitor_id === competitor.id
        ) ?? null
      : null
  );

  const competitorObservations = $derived(competitorSeries?.observations ?? []);

  /** @type {'review_count' | 'rating' | 'instagram_followers' | 'instagram_posts'} */
  let metric = $state('review_count');

  const metricOptions = /** @type {const} */ ([
    { key: 'review_count', label: 'Reviews' },
    { key: 'rating', label: 'Rating' },
    { key: 'instagram_followers', label: 'IG followers' },
    { key: 'instagram_posts', label: 'IG posts' }
  ]);

  // Compare-against picker. ``'none'`` is the default — the page is
  // first about how *this competitor* is doing, not a forced one-on-one.
  // A numeric id selects one of the user's businesses for overlay;
  // ``'all'`` shows every business of the user at once.
  /** @type {'none' | 'all' | number} */
  let compareWith = $state('none');

  const compareOptions = $derived.by(() => {
    /** @type {Array<{ key: 'none' | 'all' | number, label: string }>} */
    const out = [{ key: 'none', label: 'None' }];
    for (const b of businesses) {
      out.push({ key: b.id, label: b.name });
    }
    if (businesses.length > 1) {
      out.push({ key: 'all', label: 'All my businesses' });
    }
    return out;
  });

  // Chart wiring. The TrendChart's `business` prop is the solid line;
  // `competitors` are dashed-with-palette. When no comparison is on,
  // the competitor takes the solid slot so the user sees one clean
  // line. When a comparison is on, the user business is solid and the
  // competitor (+ optional other user businesses) ride the competitors
  // channel.
  const chartConfig = $derived.by(() => {
    if (!competitor) return null;
    const compObs = competitorObservations;
    if (compareWith === 'none') {
      return {
        business: compObs,
        businessName: competitor.name,
        competitors: []
      };
    }
    if (compareWith === 'all') {
      // First user business with any data goes solid; every other user
      // business + this competitor go dashed.
      const ranked = businesses
        .map((/** @type {any} */ b) => ({
          b,
          obs: businessTrends[b.id]?.business ?? []
        }))
        .sort((a, b) => b.obs.length - a.obs.length);
      const primary = ranked[0]?.b ?? null;
      const secondaries = ranked.slice(1);
      /** @type {any[]} */
      const competitors = [];
      for (const { b, obs } of secondaries) {
        competitors.push({
          competitor_id: -b.id,
          name: b.name,
          observations: obs
        });
      }
      competitors.push({
        competitor_id: competitor.id,
        name: competitor.name,
        observations: compObs
      });
      return {
        business: primary ? businessTrends[primary.id]?.business ?? [] : compObs,
        businessName: primary?.name ?? competitor.name,
        competitors
      };
    }
    const targetBusiness = businesses.find((/** @type {any} */ b) => b.id === compareWith);
    const targetObs = targetBusiness ? businessTrends[targetBusiness.id]?.business ?? [] : [];
    return {
      business: targetObs,
      businessName: targetBusiness?.name ?? 'Your business',
      competitors: [
        {
          competitor_id: competitor.id,
          name: competitor.name,
          observations: compObs
        }
      ]
    };
  });

  // Flat 2x2 metric grid — this competitor's latest values, with the
  // currently-selected metric highlighted to tie back to the chart.
  // ``emptyHint`` overrides the default "No reading yet" with copy
  // that tells the user *why* it's empty (e.g. IG metrics require the
  // user to provide the competitor's Instagram URL).
  const metricCards = $derived([
    {
      key: 'rating',
      label: 'Rating',
      value:
        competitor?.latest_rating != null
          ? Number(competitor.latest_rating).toFixed(1) + ' ★'
          : null,
      emptyHint: null
    },
    {
      key: 'review_count',
      label: 'Reviews',
      value:
        competitor?.latest_review_count != null
          ? String(competitor.latest_review_count)
          : null,
      emptyHint: null
    },
    {
      key: 'instagram_followers',
      label: 'IG followers',
      value:
        competitor?.latest_instagram_followers != null
          ? Number(competitor.latest_instagram_followers).toLocaleString()
          : null,
      emptyHint: competitor?.instagram_url
        ? "We'll pick this up on the next audit."
        : "Add this competitor's Instagram URL so we can read it on the next audit."
    },
    {
      key: 'instagram_posts',
      label: 'IG posts',
      value:
        competitor?.latest_instagram_posts != null
          ? String(competitor.latest_instagram_posts)
          : null,
      emptyHint: competitor?.instagram_url
        ? "We'll pick this up on the next audit."
        : "Add this competitor's Instagram URL so we can read it on the next audit."
    }
  ]);

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
</script>

<section class="space-y-6">
  <header class="space-y-2">
    <a class="btn-ghost -ml-2 text-xs" href="/dashboard/competitors">← Back to hub</a>
    {#if competitor && business}
      <h1 class="text-2xl font-semibold tracking-tight text-canvas-ink sm:text-3xl">
        {competitor.name}
      </h1>
    {/if}
  </header>

  {#if errorMessage}
    <div
      class="rounded-2xl border border-action-100 bg-action-50 p-6 text-sm text-action-700 shadow-soft"
    >
      <p class="font-semibold">We couldn't load this competitor.</p>
      <p class="mt-1 text-action-700/80">{errorMessage}</p>
      <a class="btn-ghost mt-3 inline-flex text-action-700" href="/dashboard/competitors">
        Back to hub
      </a>
    </div>
  {:else if business && competitor && chartConfig}
    <section class="space-y-4" in:fade={{ duration: 200 }}>
      <div class="card p-4 sm:p-5">
        <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <p class="text-sm font-semibold text-canvas-ink">Trend over time</p>
            <p class="text-xs text-canvas-muted">
              {#if compareWith === 'none'}
                How {competitor.name} is doing
              {:else if compareWith === 'all'}
                {competitor.name} vs all your businesses
              {:else}
                {competitor.name} vs {chartConfig.businessName}
              {/if}
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

        <!-- Compare-against picker. Default ('none') means the chart is
             a clean look at the competitor's own numbers; the user opts
             in to an overlay when they want one. -->
        <div class="mb-4">
          <p class="text-[11px] font-semibold uppercase tracking-wide text-canvas-muted">
            Compare against
          </p>
          <div class="mt-1.5 flex flex-wrap gap-1.5">
            {#each compareOptions as opt (String(opt.key))}
              {@const active = compareWith === opt.key}
              <button
                type="button"
                aria-pressed={active}
                class={`inline-flex min-h-[32px] items-center gap-1.5 rounded-full border px-3 py-1 text-xs font-medium transition ${
                  active
                    ? 'border-healthy-200 bg-healthy-50 text-healthy-700 shadow-sm'
                    : 'border-canvas-soft bg-white text-canvas-muted hover:text-canvas-ink'
                }`}
                onclick={() => (compareWith = opt.key)}
              >
                {#if active}
                  <span class="h-1.5 w-1.5 rounded-full bg-healthy-500" aria-hidden="true"></span>
                {/if}
                {opt.label}
              </button>
            {/each}
          </div>
        </div>

        <TrendChart
          business={chartConfig.business}
          competitors={chartConfig.competitors}
          businessName={chartConfig.businessName}
          {metric}
          showLegend={compareWith !== 'none'}
        />

        <p class="mt-4 text-xs text-canvas-muted">
          Not a live feed — each point lands when this competitor is rechecked.
          That happens on the weekly auto-refresh, or whenever you run an audit
          on the business that's tracking them.
        </p>
      </div>

      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {#each metricCards as card (card.key)}
          <div
            class={`card p-4 transition ${
              metric === card.key
                ? 'border-healthy-200 bg-healthy-50/40 shadow-md'
                : ''
            }`}
          >
            <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
              {card.label}
            </p>
            <p class="mt-2 text-xl font-semibold tracking-tight text-canvas-ink">
              {#if card.value != null}
                {card.value}
              {:else}
                <span class="text-sm font-normal text-canvas-muted">No reading yet</span>
              {/if}
            </p>
            {#if card.value == null && card.emptyHint}
              <p class="mt-1 text-xs text-canvas-muted">{card.emptyHint}</p>
            {/if}
          </div>
        {/each}
      </div>

      <p class="text-xs text-canvas-muted">
        {competitor.observation_count}
        {competitor.observation_count === 1 ? 'observation' : 'observations'} on file
        {#if competitor.latest_observed_at}
          · last seen {formatRelativeTime(competitor.latest_observed_at + 'Z')}
        {/if}
        · Updated when you run an audit, not live.
      </p>
    </section>

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
