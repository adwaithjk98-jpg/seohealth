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

  // The market chart treats everyone as a series on the same axis: the
  // user's own businesses go on the "business" channel of the chart
  // (solid line), and every tracked competitor across every business
  // goes on the dashed-competitor channel. We pick the first user
  // business as the "main" line so the chart's existing legend still
  // makes sense; the rest of the user's businesses ride in as
  // competitor-tinted lines labelled "Yours · <name>".
  const userBusinessSeries = $derived(
    bundles.map((/** @type {any} */ b) => ({
      competitor_id: -b.business.id, // negative so it can't collide with real comp ids
      name: bundles.length > 1 ? `Yours · ${b.business.name}` : b.business.name,
      observations: b.trends.business ?? []
    }))
  );

  const competitorSeries = $derived(
    bundles.flatMap((/** @type {any} */ b) =>
      (b.trends.competitors ?? []).map((/** @type {any} */ c) => ({
        ...c,
        name: bundles.length > 1 ? `${c.name} (for ${b.business.name})` : c.name
      }))
    )
  );

  const primaryBundle = $derived(bundles[0] ?? null);

  /** @type {'review_count' | 'rating' | 'instagram_followers' | 'instagram_posts'} */
  let metric = $state('review_count');

  /** Metric toggle options — keep in sync with TrendChart's y-axis labels. */
  const metricOptions = /** @type {const} */ ([
    { key: 'review_count', label: 'Reviews' },
    { key: 'rating', label: 'Rating' },
    { key: 'instagram_followers', label: 'IG followers' },
    { key: 'instagram_posts', label: 'IG posts' }
  ]);

  // Chart-line palette must match TrendChart.svelte exactly — these are
  // the colors the pills' dots reference.
  const BUSINESS_COLOR = '#4f8c5b';
  const COMPETITOR_PALETTE = ['#c69423', '#e2735a', '#6366f1', '#0ea5e9'];

  /**
   * Flat ordered list of every chartable entity, with stable ids + the
   * color the chart will use. The order matches the order in which they
   * get handed to TrendChart, so the palette cycling lines up 1:1 with
   * what the legend renders.
   */
  const allSeries = $derived.by(() => {
    /** @type {Array<{ id: string, kind: 'business' | 'competitor', name: string, color: string, observations: any[] }>} */
    const out = [];
    if (primaryBundle) {
      out.push({
        id: `biz-${primaryBundle.business.id}`,
        kind: 'business',
        name:
          bundles.length > 1
            ? `Yours · ${primaryBundle.business.name}`
            : primaryBundle.business.name,
        color: BUSINESS_COLOR,
        observations: primaryBundle.trends.business ?? []
      });
    }
    // Everything that goes through the competitor channel (and therefore
    // gets a palette color) — user's secondary businesses first, then
    // every real competitor.
    let paletteIdx = 0;
    for (const series of userBusinessSeries.slice(1)) {
      out.push({
        id: `userbiz-${series.competitor_id}`,
        kind: 'competitor',
        name: series.name,
        color: COMPETITOR_PALETTE[paletteIdx % COMPETITOR_PALETTE.length],
        observations: series.observations
      });
      paletteIdx += 1;
    }
    for (const series of competitorSeries) {
      out.push({
        id: `comp-${series.competitor_id}`,
        kind: 'competitor',
        name: series.name,
        color: COMPETITOR_PALETTE[paletteIdx % COMPETITOR_PALETTE.length],
        observations: series.observations ?? []
      });
      paletteIdx += 1;
    }
    return out;
  });

  /** @type {Set<string>} — series IDs the user has toggled OFF. */
  let disabledIds = $state(new Set());

  /** @param {string} id */
  function toggleSeries(id) {
    const next = new Set(disabledIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    disabledIds = next;
  }

  const chartBusiness = $derived(
    allSeries[0] && !disabledIds.has(allSeries[0].id) ? allSeries[0].observations : []
  );

  // Pass each series' explicit color through to TrendChart so the
  // dashed line matches the pill dot exactly. Without this, the chart's
  // built-in palette cycles by *visible* index and drifts away from the
  // pill colors as soon as the user toggles one off.
  const chartCompetitors = $derived(
    allSeries
      .slice(1)
      .filter((s) => !disabledIds.has(s.id))
      .map((s) => ({ ...s, color: s.color }))
  );

  const chartBusinessName = $derived(allSeries[0]?.name ?? 'Your business');

  // Phase 4.6 — transposed matrix: each entity (the user's businesses +
  // every tracked competitor) is a *column*, and each metric is a *row*.
  // The data model carries every metric we may want to show; the markup
  // just iterates through entities for each row.
  const entities = $derived(buildEntities(bundles));

  /** @param {any[]} bs */
  function buildEntities(bs) {
    /** @type {any[]} */
    const rows = [];
    for (const b of bs) {
      const trendBusiness = b.trends.business ?? [];
      const lastBizPoint = trendBusiness[trendBusiness.length - 1] ?? null;
      rows.push({
        kind: 'self',
        label: b.business.name,
        sublabel: b.business.city,
        // Overall Visibility is the deterministic 0–100 blend
        // (rating + reviews + IG followers) that the backend computes
        // identically for both sides. The full audit composite still
        // lives on the dashboard as ``latest_score``; this row uses the
        // narrower blend so the matrix is apples-to-apples.
        overall_visibility: lastBizPoint?.visibility_score ?? null,
        rating: lastBizPoint?.rating ?? null,
        review_count: lastBizPoint?.review_count ?? null,
        instagram_followers: lastBizPoint?.instagram_followers ?? null,
        instagram_posts: lastBizPoint?.instagram_posts ?? null,
        observations: trendBusiness.length
      });
      for (const comp of b.competitors ?? []) {
        rows.push({
          kind: 'competitor',
          label: comp.name,
          sublabel: `Tracked for ${b.business.name}`,
          overall_visibility: comp.latest_visibility_score ?? null,
          rating: comp.latest_rating,
          review_count: comp.latest_review_count,
          instagram_followers: comp.latest_instagram_followers ?? null,
          instagram_posts: comp.latest_instagram_posts ?? null,
          observations: comp.observation_count
        });
      }
    }
    return rows;
  }

  // Rank entities by a metric. Higher is better for every metric we
  // expose; ties share a rank. Entities with no value for a given metric
  // are not ranked.
  /**
   * @param {any[]} rows
   * @param {string} key
   */
  function rankBy(rows, key) {
    const valued = rows
      .map((r, idx) => ({ idx, value: r[key] }))
      .filter((r) => r.value != null);
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

  /** Metric rows in the transposed matrix. Each carries display +
   * formatting metadata so the markup is a single iteration.
   * @type {Array<{ key: string, label: string, hint?: string, format: (v: number) => string }>}
   */
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

  /** Map of metric.key → rank lookup table (entity idx → rank). */
  const ranks = $derived.by(() => {
    /** @type {Record<string, Record<number, number>>} */
    const out = {};
    for (const m of matrixMetrics) {
      out[m.key] = rankBy(entities, m.key);
    }
    return out;
  });

  /** @param {number} rank */
  function ordinal(rank) {
    const mod10 = rank % 10;
    const mod100 = rank % 100;
    if (mod10 === 1 && mod100 !== 11) return `${rank}st`;
    if (mod10 === 2 && mod100 !== 12) return `${rank}nd`;
    if (mod10 === 3 && mod100 !== 13) return `${rank}rd`;
    return `${rank}th`;
  }

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
      Overall market comparison
    </h1>
    <p class="mt-2 max-w-2xl text-sm leading-relaxed text-canvas-muted">
      Everyone you're tracking, stacked side by side. Switch between review count and rating to
      see the angle that matters.
    </p>
  </header>

  {#if errorMessage}
    <div
      class="rounded-2xl border border-action-100 bg-action-50 p-6 text-sm text-action-700 shadow-soft"
    >
      <p class="font-semibold">We couldn't build the market view.</p>
      <p class="mt-1 text-action-700/80">{errorMessage}</p>
    </div>
  {:else if bundles.length === 0 || (competitorSeries.length === 0 && userBusinessSeries.length === 0)}
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
        Add a competitor or two from the hub — the chart and matrix here roll up across all of
        your businesses.
      </p>
      <a class="btn-primary w-full sm:w-auto" href="/dashboard/competitors">Back to hub</a>
    </div>
  {:else}
    <div class="card p-5 sm:p-6" in:fade={{ duration: 220 }}>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="text-base font-semibold tracking-tight text-canvas-ink">Visibility over time</p>
          <p class="mt-0.5 text-xs text-canvas-muted">
            Tap a pill to hide or show that line.
          </p>
        </div>
        <!-- Metric toggle — pill-style row, scrolls horizontally on -->
        <!-- narrow viewports so all four options stay reachable. -->
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

      <!-- Series filter pills. Each pill carries the line's exact chart -->
      <!-- color via inline style so the dot stays in sync if the palette -->
      <!-- changes later. Long names truncate so a six-series market view
           reads as a tidy two-row chip rack instead of a stack of
           full-width banners (the full name stays on the title tooltip
           and in the data matrix below). -->
      <div class="mt-4 flex flex-wrap gap-1.5">
        {#each allSeries as series (series.id)}
          {@const off = disabledIds.has(series.id)}
          <button
            type="button"
            aria-pressed={!off}
            title={series.name}
            class={`group inline-flex min-h-[32px] max-w-full items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium transition ${
              off
                ? 'border-canvas-soft bg-white text-canvas-muted hover:text-canvas-ink'
                : 'border-canvas-ink/10 bg-canvas-soft/60 text-canvas-ink shadow-sm hover:border-canvas-ink/20'
            }`}
            onclick={() => toggleSeries(series.id)}
          >
            <span
              class={`h-2.5 w-2.5 shrink-0 rounded-full transition ${off ? 'opacity-30' : ''}`}
              style={`background-color: ${series.color}`}
              aria-hidden="true"
            ></span>
            <span class={`max-w-[10rem] truncate ${off ? 'line-through' : ''}`}>
              {series.name}
            </span>
          </button>
        {/each}
      </div>

      <div class="mt-5">
        <TrendChart
          business={chartBusiness}
          competitors={chartCompetitors}
          businessName={chartBusinessName}
          {metric}
          showLegend={false}
        />
      </div>

      <p class="mt-4 text-xs leading-relaxed text-canvas-muted">
        Competitor lines refresh on their own each week. Your own lines
        update whenever an audit runs — we recommend
        <a
          href="/dashboard/audit"
          class="font-medium text-healthy-700 underline-offset-2 hover:underline"
        >
          setting up auto-audits
        </a>
        so they keep pace automatically, or you can always run a manual
        audit from there.
      </p>
    </div>

    <!-- Transposed data matrix: columns = entities (You + competitors), -->
    <!-- rows = metrics. The first column is sticky on mobile so the user -->
    <!-- can scroll horizontally without losing the metric label. -->
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
        <table class="w-full min-w-[640px] text-sm">
          <thead>
            <!-- Solid backgrounds only in this table: the sticky first
                 column previously used translucent fills (/30, /60 +
                 blur), so horizontally-scrolled values ghosted through
                 the Metric labels on the odd stripes. -->
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
        Ranks are derived locally from the latest observation per column. Cells with no value
        yet show "—" and aren't ranked. Overall visibility is a deterministic 0–100 blend of
        rating, reviews, and Instagram followers — computed identically for you and every
        competitor so the row is apples-to-apples.
      </p>
    </section>
  {/if}
</section>
