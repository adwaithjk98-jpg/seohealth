<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fade } from 'svelte/transition';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import TrendChart from '$lib/components/TrendChart.svelte';

  /**
   * @type {{
   *   data: {
   *     businesses: any[] | null,
   *     bundles: any[],
   *     error: string | null
   *   }
   * }}
   */
  let { data } = $props();

  const bundles = $derived(data?.bundles ?? []);
  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );

  // One business at a time. The market view used to flatten every business
  // and every competitor onto a single axis — six legend pills before the
  // first data point. Now the business tiles below double as the scope
  // switcher AND the side-by-side glance across your businesses; the chart,
  // headline, and matrix all follow the selected business.
  /** @type {number | null} */
  let selectedId = $state(null);

  // Default to the first business that actually tracks competitors — landing
  // on an empty comparison when a populated one exists is a dead first paint.
  const selected = $derived(
    bundles.find((/** @type {any} */ b) => b.business.id === selectedId) ??
      bundles.find((/** @type {any} */ b) => (b.competitors ?? []).length > 0) ??
      bundles[0] ??
      null
  );

  /** @type {'review_count' | 'rating' | 'instagram_followers' | 'instagram_posts'} */
  let metric = $state('review_count');

  const metricOptions = /** @type {const} */ ([
    { key: 'review_count', label: 'Reviews' },
    { key: 'rating', label: 'Rating' },
    { key: 'instagram_followers', label: 'IG followers' },
    { key: 'instagram_posts', label: 'IG posts' }
  ]);

  // ---- business tiles (switcher + overview) -------------------------------
  /** Latest + previous visibility blend for a bundle's own line. */
  /** @param {any} b */
  function visibilityPair(b) {
    const obs = (b.trends.business ?? []).filter(
      (/** @type {any} */ p) => p.visibility_score != null
    );
    const last = obs[obs.length - 1] ?? null;
    const prev = obs[obs.length - 2] ?? null;
    return {
      score: last ? Math.round(last.visibility_score) : null,
      delta:
        last && prev ? Math.round(last.visibility_score) - Math.round(prev.visibility_score) : null
    };
  }

  const tiles = $derived(
    bundles.map((/** @type {any} */ b) => ({
      id: b.business.id,
      name: b.business.name,
      city: b.business.city,
      competitors: (b.competitors ?? []).length,
      ...visibilityPair(b)
    }))
  );

  // Keep the active tile visible — the default selection may not be the
  // first tile (it prefers a business with competitors), and a selection
  // hidden off the edge of the scroll row reads as "nothing selected".
  /** @type {HTMLDivElement | null} */
  let tileRow = $state(null);

  $effect(() => {
    void selected?.business.id;
    tileRow
      ?.querySelector('[aria-selected="true"]')
      ?.scrollIntoView({ inline: 'center', block: 'nearest', behavior: 'instant' });
  });

  // ---- chart series for the selected business -----------------------------
  const chartBusiness = $derived(selected?.trends.business ?? []);
  const chartCompetitors = $derived(
    (selected?.trends.competitors ?? []).map((/** @type {any} */ c) => ({
      competitor_id: c.competitor_id,
      name: c.name,
      observations: c.observations ?? []
    }))
  );

  // ---- the insight headline ------------------------------------------------
  // Deterministic, computed from the same latest values the matrix shows.
  // The chart illustrates this sentence; the sentence is the product.
  const METRIC_META = {
    review_count: { latest: 'latest_review_count', noun: 'reviews', unit: (/** @type {number} */ v) => `${Math.round(v)} ${Math.abs(v) === 1 ? 'review' : 'reviews'}` },
    rating: { latest: 'latest_rating', noun: 'rating', unit: (/** @type {number} */ v) => `${v.toFixed(1)} ★` },
    instagram_followers: { latest: 'latest_instagram_followers', noun: 'IG followers', unit: (/** @type {number} */ v) => `${v >= 10000 ? Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(v) : Math.round(v).toLocaleString('en')} followers` },
    instagram_posts: { latest: 'latest_instagram_posts', noun: 'IG posts', unit: (/** @type {number} */ v) => `${Math.round(v)} ${Math.abs(v) === 1 ? 'post' : 'posts'}` }
  };

  /** @param {number} rank */
  function ordinal(rank) {
    const mod10 = rank % 10;
    const mod100 = rank % 100;
    if (mod10 === 1 && mod100 !== 11) return `${rank}st`;
    if (mod10 === 2 && mod100 !== 12) return `${rank}nd`;
    if (mod10 === 3 && mod100 !== 13) return `${rank}rd`;
    return `${rank}th`;
  }

  // Business names often end in an abbreviation ("… Pvt. Ltd.") — a sentence
  // period straight after reads as a typo, so sentences that end on a name
  // skip their own full stop when the name already carries one.
  /** @param {string} name */
  function endStop(name) {
    return name.trimEnd().endsWith('.') ? '' : '.';
  }

  const insight = $derived.by(() => {
    if (!selected) return null;
    const meta = METRIC_META[metric];
    const own = (selected.trends.business ?? [])
      .map((/** @type {any} */ p) => p[metric])
      .filter((/** @type {any} */ v) => v != null);
    const you = own.length ? Number(own[own.length - 1]) : null;
    const rivals = (selected.competitors ?? [])
      .map((/** @type {any} */ c) => ({ name: c.name, value: c[meta.latest] }))
      .filter((/** @type {any} */ c) => c.value != null)
      .map((/** @type {any} */ c) => ({ ...c, value: Number(c.value) }))
      .sort((/** @type {any} */ a, /** @type {any} */ b) => b.value - a.value);

    if ((selected.competitors ?? []).length === 0) {
      return { text: 'No competitors tracked for this business yet — add one from the hub to see how you stack up.', tone: 'muted' };
    }
    if (you == null && rivals.length === 0) {
      return { text: 'First readings land with your next audit and the weekly competitor refresh.', tone: 'muted' };
    }
    if (you == null) {
      return { text: `Your ${meta.noun} line starts with your next audit — the market is already drawn in.`, tone: 'muted' };
    }
    if (rivals.length === 0) {
      return { text: `Competitor ${meta.noun} arrive with the next weekly refresh.`, tone: 'muted' };
    }
    const ahead = rivals.filter((/** @type {any} */ c) => c.value > you).length;
    const rank = ahead + 1;
    const total = rivals.length + 1;
    if (rank === 1) {
      const runnerUp = rivals[0];
      const gap = you - runnerUp.value;
      if (gap === 0) return { text: `You're tied with ${runnerUp.name} at the top on ${meta.noun}.`, tone: 'lead' };
      return { text: `You lead on ${meta.noun} — ${meta.unit(gap)} ahead of ${runnerUp.name}${endStop(runnerUp.name)}`, tone: 'lead' };
    }
    const leader = rivals[0];
    const gap = leader.value - you;
    return {
      text: `${leader.name} leads by ${meta.unit(gap)} — you're ${ordinal(rank)} of ${total}.`,
      tone: 'chase'
    };
  });

  // ---- matrix, scoped to the selected business -----------------------------
  const entities = $derived.by(() => {
    if (!selected) return [];
    /** @type {any[]} */
    const rows = [];
    const trendBusiness = selected.trends.business ?? [];
    const lastBizPoint = trendBusiness[trendBusiness.length - 1] ?? null;
    rows.push({
      kind: 'self',
      label: selected.business.name,
      sublabel: selected.business.city,
      overall_visibility: lastBizPoint?.visibility_score ?? null,
      rating: lastBizPoint?.rating ?? null,
      review_count: lastBizPoint?.review_count ?? null,
      instagram_followers: lastBizPoint?.instagram_followers ?? null,
      instagram_posts: lastBizPoint?.instagram_posts ?? null
    });
    for (const comp of selected.competitors ?? []) {
      rows.push({
        kind: 'competitor',
        label: comp.name,
        sublabel: null,
        overall_visibility: comp.latest_visibility_score ?? null,
        rating: comp.latest_rating,
        review_count: comp.latest_review_count,
        instagram_followers: comp.latest_instagram_followers ?? null,
        instagram_posts: comp.latest_instagram_posts ?? null
      });
    }
    return rows;
  });

  /**
   * @param {any[]} rows
   * @param {string} key
   */
  function rankBy(rows, key) {
    const valued = rows
      .map((r, idx) => ({ idx, value: r[key] }))
      .filter((r) => r.value != null);
    // A rank of one is no rank — "(1st)" with zero rivals reads as a joke.
    if (valued.length < 2) return {};
    valued.sort((a, b) => Number(b.value) - Number(a.value));
    /** @type {Record<number, number>} */
    const out = {};
    let lastValue = /** @type {number | null} */ (null);
    let lastRank = 0;
    valued.forEach((row, position) => {
      const rank = lastValue !== null && lastValue === Number(row.value) ? lastRank : position + 1;
      out[row.idx] = rank;
      lastValue = Number(row.value);
      lastRank = rank;
    });
    return out;
  }

  /** @type {Array<{ key: string, label: string, hint?: string, format: (v: number) => string }>} */
  const matrixMetrics = [
    {
      key: 'overall_visibility',
      label: 'Overall visibility',
      hint: 'Blended score (0–100)',
      format: (v) => String(Math.round(v))
    },
    { key: 'rating', label: 'Rating', format: (v) => v.toFixed(1) + ' ★' },
    { key: 'review_count', label: 'Reviews', format: (v) => String(Math.round(v)) },
    {
      key: 'instagram_followers',
      label: 'Instagram followers',
      format: (v) => Number(v).toLocaleString()
    },
    {
      key: 'instagram_posts',
      label: 'Instagram posts',
      format: (v) => String(Math.round(v))
    }
  ];

  const ranks = $derived.by(() => {
    /** @type {Record<string, Record<number, number>>} */
    const out = {};
    for (const m of matrixMetrics) {
      out[m.key] = rankBy(entities, m.key);
    }
    return out;
  });

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user || data?.error === 'unauthenticated') {
      await goto('/login', { replaceState: true });
    }
  });
</script>

<svelte:head><title>Market comparison · SEO Health</title></svelte:head>

<section class="space-y-6">
  <header>
    <a class="btn-ghost -ml-2 text-xs" href="/dashboard/competitors">← Back to hub</a>
    <h1 class="mt-3 text-2xl font-semibold tracking-tight text-canvas-ink sm:text-3xl">
      Market comparison
    </h1>
  </header>

  {#if errorMessage}
    <div
      class="rounded-2xl border border-action-100 bg-action-50 p-6 text-sm text-action-700 shadow-soft"
    >
      <p class="font-semibold">We couldn't build the market view.</p>
      <p class="mt-1 text-action-700/80">{errorMessage}</p>
    </div>
  {:else if bundles.length === 0}
    <div
      class="card mx-auto flex max-w-md flex-col items-center gap-4 px-6 py-12 text-center sm:px-10"
    >
      <div
        class="grid h-16 w-16 place-items-center rounded-2xl bg-healthy-50 text-3xl"
        aria-hidden="true"
      >
        🪟
      </div>
      <h2 class="text-lg font-semibold tracking-tight text-canvas-ink">Nothing to compare yet</h2>
      <p class="text-sm leading-relaxed text-canvas-muted">
        Add a competitor or two from the hub — this page shows how each of your businesses
        stacks up against the rivals it tracks.
      </p>
      <a class="btn-primary w-full sm:w-auto" href="/dashboard/competitors">Back to hub</a>
    </div>
  {:else}
    <!-- Business tiles: the side-by-side glance across your businesses, and
         the switch that scopes everything below to one of them. -->
    {#if tiles.length > 1}
      <div
        bind:this={tileRow}
        class="-mx-1 flex gap-2 overflow-x-auto px-1 pb-1"
        role="tablist"
        aria-label="Choose a business"
      >
        {#each tiles as tile (tile.id)}
          {@const active = selected?.business.id === tile.id}
          <button
            type="button"
            role="tab"
            aria-selected={active}
            class={`min-w-[9.5rem] shrink-0 rounded-2xl border px-4 py-3 text-left transition ${
              active
                ? 'border-healthy-500/60 bg-white shadow-soft'
                : 'border-canvas-soft bg-white/60 hover:border-canvas-ink/15'
            }`}
            onclick={() => (selectedId = tile.id)}
          >
            <p class={`truncate text-sm font-semibold ${active ? 'text-canvas-ink' : 'text-canvas-muted'}`}>
              {tile.name}
            </p>
            <p class="mt-1.5 flex items-baseline gap-1.5">
              <span class={`text-xl font-semibold tracking-tight ${active ? 'text-healthy-700' : 'text-canvas-ink/70'}`}>
                {tile.score ?? '—'}
              </span>
              {#if tile.delta != null && tile.delta !== 0}
                <span class="text-[11px] font-medium text-canvas-muted">
                  {tile.delta > 0 ? '↑' : '↓'}{Math.abs(tile.delta)}
                </span>
              {/if}
            </p>
            <p class="mt-0.5 truncate text-[11px] text-canvas-muted">
              {tile.competitors} {tile.competitors === 1 ? 'competitor' : 'competitors'}
            </p>
          </button>
        {/each}
      </div>
    {/if}

    {#if selected}
      <div class="card p-5 sm:p-6" in:fade={{ duration: 220 }}>
        <div class="flex flex-wrap items-start justify-between gap-3">
          <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
            Visibility over time
            {#if tiles.length > 1}
              <span class="font-normal normal-case tracking-normal">· {selected.business.name}</span>
            {/if}
          </p>
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

        {#if insight}
          <p
            class={`mt-2 max-w-xl text-[15px] font-medium leading-snug tracking-tight sm:text-base ${
              insight.tone === 'muted' ? 'text-canvas-muted' : 'text-canvas-ink'
            }`}
          >
            {insight.text}
          </p>
        {/if}

        <div class="mt-4">
          <TrendChart
            business={chartBusiness}
            competitors={chartCompetitors}
            businessName="You"
            {metric}
            showLegend={true}
          />
        </div>

        <p class="mt-3 text-[11px] text-canvas-muted">
          Competitors refresh weekly · your line updates with each audit ·
          <a
            href="/dashboard/audit"
            class="font-medium text-healthy-700 underline-offset-2 hover:underline">auto-audits →</a
          >
        </p>
      </div>

      <!-- Data matrix: the chart's table twin, same scope. -->
      <section class="space-y-4">
        <div class="flex items-end justify-between gap-3">
          <h2 class="text-sm font-semibold uppercase tracking-wide text-canvas-muted">
            Data matrix
          </h2>
          <span class="text-xs text-canvas-muted">
            {entities.length} {entities.length === 1 ? 'entity' : 'entities'} ·
            {matrixMetrics.length} metrics
          </span>
        </div>

        <div class="card overflow-x-auto p-0">
          <table class="w-full min-w-[480px] text-sm">
            <thead>
              <tr
                class="border-b border-canvas-soft bg-canvas-soft text-xs uppercase tracking-wide text-canvas-muted"
              >
                <th
                  class="sticky left-0 z-10 border-r border-canvas-soft bg-canvas-soft px-5 py-4 text-left font-semibold"
                >
                  Metric
                </th>
                {#each entities as entity, eidx (eidx)}
                  <th
                    class={`px-5 py-4 text-right font-semibold ${entity.kind === 'self' ? 'text-healthy-700' : 'text-canvas-muted'}`}
                  >
                    <p class="truncate text-sm normal-case tracking-normal">
                      {entity.label}
                      {#if entity.kind === 'self'}
                        <span
                          class="ml-1 inline-flex items-center rounded-full bg-healthy-100 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-healthy-700"
                        >
                          You
                        </span>
                      {/if}
                    </p>
                    {#if entity.sublabel}
                      <p class="mt-0.5 truncate text-[10px] font-normal normal-case text-canvas-muted">
                        {entity.sublabel}
                      </p>
                    {/if}
                  </th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each matrixMetrics as m, midx (m.key)}
                <tr
                  class={`border-b border-canvas-soft/50 last:border-0 ${midx % 2 === 0 ? 'bg-white' : 'bg-canvas'}`}
                >
                  <th
                    class={`sticky left-0 z-10 border-r border-canvas-soft px-5 py-5 text-left ${midx % 2 === 0 ? 'bg-white' : 'bg-canvas'}`}
                    scope="row"
                  >
                    <p class="text-sm font-semibold text-canvas-ink">{m.label}</p>
                    {#if m.hint}
                      <p class="mt-0.5 text-[11px] font-normal text-canvas-muted">{m.hint}</p>
                    {/if}
                  </th>
                  {#each entities as entity, eidx (eidx)}
                    {@const value = entity[m.key]}
                    {@const rank = ranks[m.key]?.[eidx] ?? null}
                    <td
                      class={`px-5 py-5 text-right align-top ${entity.kind === 'self' ? 'bg-healthy-50/30' : ''}`}
                    >
                      {#if value != null}
                        <div class="font-semibold text-canvas-ink">{m.format(value)}</div>
                        {#if rank != null}
                          <div
                            class={`mt-1 text-xs font-bold ${rank === 1 ? 'text-healthy-700' : 'text-canvas-muted'}`}
                          >
                            ({ordinal(rank)})
                          </div>
                        {/if}
                      {:else}
                        <div class="text-canvas-muted">—</div>
                      {/if}
                    </td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
        <p class="text-xs text-canvas-muted">
          Latest reading per column; unranked cells show "—". Overall visibility blends rating,
          reviews and Instagram followers the same way for both sides.
        </p>
      </section>
    {/if}
  {/if}
</section>
