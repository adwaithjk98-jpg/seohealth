<script>
  import { onMount } from 'svelte';
  import { goto, invalidateAll } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import { getCompetitorInsights } from '$lib/api.js';
  import { formatRelativeTime } from '$lib/dashboard.js';
  import ManualAddCompetitorModal from '$lib/components/ManualAddCompetitorModal.svelte';

  /** @type {{ data: { businesses: any[] | null, competitors: any[], error: string | null } }} */
  let { data } = $props();

  const businesses = $derived(data?.businesses ?? []);
  const competitors = $derived(data?.competitors ?? []);
  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );

  const subState = $derived(authState.user?.subscription_state ?? null);
  const tier = $derived(subState?.tier ?? authState.user?.plan ?? 'free');
  const isPaid = $derived(tier === 'paid');
  // Phase 4.6 — the cap is now a total across all the user's businesses,
  // not per-business. `competitorLimit` reads straight from the tier
  // payload (paid: 4 today); the Hub counter mirrors it as `X / 4`.
  const competitorLimit = $derived(subState?.limits?.competitors ?? 0);
  const atCap = $derived(competitorLimit > 0 && competitors.length >= competitorLimit);

  let manualAddOpen = $state(false);

  function openManualAdd() {
    manualAddOpen = true;
  }

  function closeManualAdd() {
    manualAddOpen = false;
  }

  async function handleManualAdded() {
    // Refresh the loader so the new competitor shows up in the list right
    // away. The modal stays open on its success state — closing is the
    // user's call.
    await invalidateAll();
    await loadInsights();
  }

  // Insight cards (deterministic math + LLM phrasing on the backend). We
  // fetch one set per business and flatten — paid users cap at 3
  // businesses, so the fan-out is bounded and cheap.
  /** @type {any[]} */
  let insightCards = $state([]);
  let insightsLoading = $state(false);
  let insightsError = $state(/** @type {string | null} */ (null));

  async function loadInsights() {
    if (!businesses.length || !competitors.length) {
      insightCards = [];
      return;
    }
    insightsLoading = true;
    insightsError = null;
    try {
      const settled = await Promise.allSettled(
        businesses.map((/** @type {any} */ b) => getCompetitorInsights(b.id))
      );
      /** @type {any[]} */
      const cards = [];
      for (const r of settled) {
        if (r.status === 'fulfilled') {
          for (const c of r.value.cards ?? []) {
            cards.push({ ...c, business_id: r.value.business_id });
          }
        }
      }
      insightCards = cards;
    } catch (err) {
      insightsError = err instanceof Error ? err.message : 'Could not load insights.';
    } finally {
      insightsLoading = false;
    }
  }

  // Re-fetch whenever the loader hands us fresh competitor data (e.g.
  // after a successful manual add or a discovery Track).
  $effect(() => {
    void competitors.length;
    void businesses.length;
    if (businesses.length > 0 && competitors.length > 0) {
      loadInsights();
    } else {
      insightCards = [];
    }
  });

  /** @param {any} card */
  function metricValue(card) {
    if (card.fact.metric === 'rating') {
      return Number(card.fact.user_value).toFixed(1);
    }
    return String(Math.round(card.fact.user_value));
  }

  /** @param {any} card */
  function metricUnit(card) {
    return card.fact.metric === 'rating' ? '★' : 'reviews';
  }

  /** @param {any} card */
  function deltaLabel(card) {
    if (card.fact.kind === 'matched') return 'On par with avg';
    const sign = card.fact.delta >= 0 ? '+' : '';
    const value =
      card.fact.metric === 'rating'
        ? card.fact.delta.toFixed(1)
        : String(Math.round(card.fact.delta));
    return `${sign}${value} vs avg`;
  }

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user || data?.error === 'unauthenticated') {
      await goto('/login', { replaceState: true });
    }
  });
</script>

<section class="space-y-8">
  {#if errorMessage}
    <div
      class="rounded-2xl border border-action-100 bg-action-50 p-6 text-sm text-action-700 shadow-soft"
      in:fade={{ duration: 220 }}
    >
      <p class="font-semibold">We couldn't load your competitors right now.</p>
      <p class="mt-1 text-action-700/80">{errorMessage}</p>
      <button
        type="button"
        class="btn-ghost mt-3 inline-flex text-action-700"
        onclick={() => location.reload()}
      >
        ↻ Try again
      </button>
    </div>

  {:else if businesses.length === 0}
    <!-- No businesses owned — gentle redirect to onboarding. Centered + -->
    <!-- generous so it doesn't feel like a dead-end. -->
    <div
      class="card mx-auto flex max-w-md flex-col items-center gap-4 px-6 py-12 text-center sm:px-10"
      in:fade={{ duration: 260 }}
    >
      <div
        class="grid h-16 w-16 place-items-center rounded-2xl bg-healthy-50 text-3xl"
        aria-hidden="true"
      >
        🏢
      </div>
      <h2 class="text-xl font-semibold tracking-tight text-canvas-ink">Add a business first</h2>
      <p class="text-sm leading-relaxed text-canvas-muted">
        Competitor tracking is anchored to a business you own. Add one to get started — we'll do
        the rest.
      </p>
      <a class="btn-primary w-full sm:w-auto" href="/">Add a business</a>
    </div>

  {:else if !isPaid}
    <header in:fade={{ duration: 240 }}>
      <span
        class="inline-flex items-center gap-2 rounded-full border border-attention-200 bg-attention-50 px-3 py-1 text-xs font-medium text-attention-700"
      >
        <span class="h-1.5 w-1.5 rounded-full bg-attention-500"></span>
        Competitor Intelligence
      </span>
      <h1 class="mt-4 text-2xl font-semibold tracking-tight text-canvas-ink sm:text-3xl">
        See how you stack up against the local market
      </h1>
      <p class="mt-2 max-w-2xl text-sm leading-relaxed text-canvas-muted">
        Track up to 3 nearby businesses per location and watch the gap close — or widen — over
        time.
      </p>
    </header>
    <div
      class="card flex flex-col gap-4 border-attention-100 bg-gradient-to-br from-attention-50 to-white p-6 sm:flex-row sm:items-center sm:justify-between sm:p-7"
    >
      <div class="flex items-start gap-4">
        <div
          class="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-attention-100 text-2xl"
          aria-hidden="true"
        >
          ✨
        </div>
        <div class="text-sm">
          <p class="font-semibold text-canvas-ink">Competitor tracking is a paid feature</p>
          <p class="mt-1 text-canvas-muted">
            Upgrade to unlock discovery and 1-on-1 deep dives against the local market.
          </p>
        </div>
      </div>
      <a class="btn-primary w-full shrink-0 sm:w-auto" href="/billing">Upgrade to paid</a>
    </div>

  {:else if competitors.length === 0}
    <!-- Populated empty state: paid user with no competitors tracked. -->
    <!-- Centered hero so the primary CTA leads the eye. -->
    <div
      class="card mx-auto flex max-w-2xl flex-col items-center gap-5 px-6 py-12 text-center sm:px-10 sm:py-16"
      in:fly={{ y: 8, duration: 280, easing: quintOut }}
    >
      <div
        class="grid h-20 w-20 place-items-center rounded-3xl bg-healthy-50 text-4xl shadow-soft"
        aria-hidden="true"
      >
        🔭
      </div>
      <span
        class="inline-flex items-center gap-2 rounded-full border border-healthy-200 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
      >
        <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
        Competitor Intelligence
      </span>
      <h1 class="text-2xl font-semibold tracking-tight text-canvas-ink sm:text-3xl">
        See how you stack up
        <span class="block text-canvas-ink/90">against the local market</span>
      </h1>
      <p class="max-w-md text-sm leading-relaxed text-canvas-muted">
        We'll scan your area for similar businesses and quietly track their visibility next to
        yours. No charts to chase — just a calm read of where you sit.
      </p>
      <div class="flex w-full flex-col gap-2 sm:w-auto sm:flex-row sm:items-center">
        <a class="btn-primary w-full sm:w-auto" href="/dashboard/competitors/discover">
          Find similar businesses
        </a>
        <button type="button" class="btn-ghost w-full sm:w-auto" onclick={openManualAdd}>
          Add manually
        </button>
      </div>
    </div>

  {:else}
    <header in:fade={{ duration: 220 }}>
      <span
        class="inline-flex items-center gap-2 rounded-full border border-healthy-200 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
      >
        <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
        Market at a Glance
      </span>
      <h1 class="mt-4 text-2xl font-semibold tracking-tight text-canvas-ink sm:text-3xl">
        Your competitive landscape
      </h1>
      <p class="mt-2 text-sm leading-relaxed text-canvas-muted">
        {competitors.length}
        {competitors.length === 1 ? 'competitor' : 'competitors'} tracked across {businesses.length}
        {businesses.length === 1 ? 'business' : 'businesses'}.
      </p>
    </header>

    <!-- Insights — proper metric cards with the value as hero, the LLM -->
    <!-- (or deterministic) sentence underneath. Tinted by kind. -->
    <section aria-labelledby="insights-heading" class="space-y-3">
      <div class="flex items-end justify-between">
        <h2 id="insights-heading" class="text-sm font-semibold uppercase tracking-wide text-canvas-muted">
          Insights
        </h2>
        {#if insightsLoading}
          <span
            class="inline-flex items-center gap-1.5 rounded-full bg-canvas-soft px-2.5 py-0.5 text-xs font-medium text-canvas-muted"
          >
            <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-canvas-muted/70"></span>
            Refreshing
          </span>
        {/if}
      </div>
      {#if insightsError}
        <div
          class="rounded-2xl border border-action-100 bg-action-50 p-4 text-xs text-action-700 shadow-soft"
        >
          {insightsError}
        </div>
      {:else if insightCards.length === 0}
        <div
          class="rounded-2xl border border-dashed border-canvas-soft bg-white/60 p-6 text-sm text-canvas-muted"
          in:fade={{ duration: 220 }}
        >
          We'll surface your top winning factor and biggest opportunity here once we have
          observations from both you and your competitors.
        </div>
      {:else}
        <div class="grid gap-3 sm:grid-cols-2">
          {#each insightCards as card, idx (`${card.business_id}-${card.fact.metric}-${card.fact.kind}`)}
            {@const kind = card.fact.kind}
            {@const cardClass =
              kind === 'winning'
                ? 'border-healthy-100 bg-gradient-to-br from-healthy-50/70 to-white'
                : kind === 'matched'
                  ? 'border-canvas-soft bg-gradient-to-br from-canvas-soft/40 to-white'
                  : 'border-attention-100 bg-gradient-to-br from-attention-50/70 to-white'}
            {@const badgeClass =
              kind === 'winning'
                ? 'bg-healthy-100 text-healthy-700'
                : kind === 'matched'
                  ? 'bg-canvas-soft text-canvas-muted'
                  : 'bg-attention-100 text-attention-700'}
            {@const dotClass =
              kind === 'winning'
                ? 'bg-healthy-500'
                : kind === 'matched'
                  ? 'bg-canvas-muted'
                  : 'bg-attention-500'}
            {@const deltaClass =
              kind === 'winning'
                ? 'text-healthy-700'
                : kind === 'matched'
                  ? 'text-canvas-muted'
                  : 'text-attention-700'}
            {@const badgeLabel =
              kind === 'winning' ? 'Winning' : kind === 'matched' ? 'Matched' : 'Opportunity'}
            <article
              class={`card relative overflow-hidden p-5 transition hover:shadow-md ${cardClass}`}
              in:fly={{ y: 6, delay: 40 * idx, duration: 240, easing: quintOut }}
            >
              <div class="flex items-center justify-between gap-3">
                <span
                  class={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${badgeClass}`}
                >
                  <span class={`h-1.5 w-1.5 rounded-full ${dotClass}`}></span>
                  {badgeLabel}
                </span>
                <span class={`text-xs font-medium ${deltaClass}`}>
                  {deltaLabel(card)}
                </span>
              </div>

              <p class="mt-4 text-xs font-medium uppercase tracking-wide text-canvas-muted">
                {card.headline.split('·')[1]?.trim() ?? card.headline}
              </p>
              <p class="mt-1 flex items-baseline gap-1.5 text-canvas-ink">
                <span class="text-3xl font-semibold tracking-tight">{metricValue(card)}</span>
                <span class="text-sm text-canvas-muted">{metricUnit(card)}</span>
              </p>

              <p class="mt-4 text-sm leading-relaxed text-canvas-ink/80">{card.sentence}</p>

              <p class="mt-4 border-t border-canvas-soft/70 pt-3 text-xs text-canvas-muted">
                Competitor avg
                <span class="font-medium text-canvas-ink">
                  {card.fact.metric === 'rating'
                    ? Number(card.fact.competitor_average).toFixed(1) + ' ★'
                    : Math.round(card.fact.competitor_average)}
                </span>
                · {card.fact.competitor_sample_size}
                {card.fact.competitor_sample_size === 1 ? 'competitor' : 'competitors'}
              </p>
            </article>
          {/each}
        </div>
      {/if}
    </section>

    <!-- Master Overview CTA — full-width hover-card with chevron. -->
    <a
      href="/dashboard/competitors/market"
      class="card group flex w-full items-center justify-between gap-4 p-6 transition hover:-translate-y-0.5 hover:border-healthy-200 hover:shadow-md"
      in:fly={{ y: 8, duration: 260, easing: quintOut }}
    >
      <div class="flex items-start gap-4 min-w-0">
        <div
          class="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-healthy-50 text-xl"
          aria-hidden="true"
        >
          📊
        </div>
        <div class="min-w-0">
          <p class="text-base font-semibold tracking-tight text-canvas-ink">
            View overall market comparison
          </p>
          <p class="mt-1 text-sm text-canvas-muted">
            A birds-eye chart and matrix of every competitor you're tracking.
          </p>
        </div>
      </div>
      <span
        class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-canvas-soft text-canvas-muted transition group-hover:bg-healthy-500 group-hover:text-white"
        aria-hidden="true">→</span
      >
    </a>

    <!-- Tracked list — horizontal hover-cards with chevron. -->
    <section class="space-y-4">
      <div class="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 class="text-sm font-semibold uppercase tracking-wide text-canvas-muted">
            My competitors
          </h2>
          <p class="mt-0.5 text-sm text-canvas-ink">
            <span class="font-semibold">{competitors.length}</span>{competitorLimit > 0
              ? `/${competitorLimit}`
              : ''}
            <span class="text-canvas-muted">added</span>
            {#if atCap}
              <span
                class="ml-2 inline-flex items-center gap-1 rounded-full bg-attention-100 px-2 py-0.5 text-xs font-medium text-attention-700"
              >
                <span class="h-1.5 w-1.5 rounded-full bg-attention-500"></span>
                At plan limit
              </span>
            {/if}
          </p>
        </div>
        <div class="flex gap-2">
          {#if atCap}
            <span
              class="inline-flex items-center gap-1 rounded-full bg-canvas-soft px-3 py-1.5 text-xs text-canvas-muted"
              title="You've reached your plan's competitor cap. Remove one to add another."
            >
              Limit reached
            </span>
          {:else}
            <a class="btn-ghost text-xs" href="/dashboard/competitors/discover">Discover more</a>
            <button type="button" class="btn-ghost text-xs" onclick={openManualAdd}>
              + Add manually
            </button>
          {/if}
        </div>
      </div>

      {#if atCap}
        <div
          class="rounded-2xl border border-attention-100 bg-attention-50/60 p-4 text-sm text-canvas-ink"
        >
          <p class="font-medium">You're tracking the maximum {competitorLimit} competitors.</p>
          <p class="mt-1 text-xs text-canvas-muted">
            Remove one below to swap in a new competitor, or stay on this lineup to build
            stronger trend lines over time.
          </p>
        </div>
      {/if}

      <ul class="space-y-3">
        {#each competitors as competitor, i (competitor.id)}
          <li in:fly={{ y: 6, delay: 30 * i, duration: 240, easing: quintOut }}>
            <a
              href={`/businesses/${competitor.business_id}/competitors/${competitor.id}`}
              class="card group flex items-center gap-4 p-5 transition hover:-translate-y-0.5 hover:border-healthy-200 hover:shadow-md"
            >
              <div
                class="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-canvas-soft text-base font-semibold uppercase tracking-tight text-canvas-ink"
                aria-hidden="true"
              >
                {(competitor.name ?? '?').slice(0, 1)}
              </div>

              <div class="min-w-0 flex-1">
                <p class="truncate text-base font-semibold tracking-tight text-canvas-ink">
                  {competitor.name}
                </p>
                <p class="mt-0.5 text-xs text-canvas-muted">
                  Tracked for
                  <span class="font-medium text-canvas-ink/80">{competitor.business_name}</span>
                  {#if competitor.business_city}
                    · {competitor.business_city}
                  {/if}
                </p>

                <div class="mt-2 flex flex-wrap items-center gap-2">
                  {#if competitor.latest_rating != null}
                    <span
                      class="inline-flex items-center gap-1 rounded-full bg-healthy-50 px-2 py-0.5 text-xs font-medium text-healthy-700"
                    >
                      {competitor.latest_rating.toFixed(1)} ★
                    </span>
                    {#if competitor.latest_review_count != null}
                      <span
                        class="inline-flex items-center gap-1 rounded-full bg-canvas-soft px-2 py-0.5 text-xs font-medium text-canvas-ink/80"
                      >
                        {competitor.latest_review_count} reviews
                      </span>
                    {/if}
                    {#if competitor.latest_observed_at}
                      <span class="text-xs text-canvas-muted">
                        · seen {formatRelativeTime(competitor.latest_observed_at + 'Z')}
                      </span>
                    {/if}
                  {:else if competitor.observation_count === 0}
                    <span
                      class="inline-flex items-center gap-1 rounded-full bg-canvas-soft px-2 py-0.5 text-xs font-medium text-canvas-muted"
                    >
                      <span class="h-1.5 w-1.5 rounded-full bg-canvas-muted/60"></span>
                      Awaiting next audit
                    </span>
                  {:else}
                    <span
                      class="inline-flex items-center gap-1 rounded-full bg-attention-50 px-2 py-0.5 text-xs font-medium text-attention-700"
                    >
                      <span class="h-1.5 w-1.5 rounded-full bg-attention-500"></span>
                      Last audit couldn't read it
                    </span>
                  {/if}
                </div>
              </div>

              <span
                class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-canvas-soft text-canvas-muted transition group-hover:bg-healthy-500 group-hover:text-white"
                aria-hidden="true">›</span
              >
            </a>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</section>

{#if manualAddOpen && businesses.length > 0}
  <ManualAddCompetitorModal
    {businesses}
    defaultBusinessId={businesses[0]?.id ?? null}
    onClose={closeManualAdd}
    onAdded={handleManualAdded}
  />
{/if}
