<script>
  import { onMount, onDestroy } from 'svelte';
  import {
    Chart,
    LineController,
    LineElement,
    PointElement,
    LinearScale,
    TimeSeriesScale,
    Tooltip,
    Legend,
    Filler
  } from 'chart.js';

  // Time scale needs adapter-date-fns to parse the ISO timestamps we ship from
  // the backend. Pulled in once here at module scope.
  import 'chartjs-adapter-date-fns';

  Chart.register(
    LineController,
    LineElement,
    PointElement,
    LinearScale,
    TimeSeriesScale,
    Tooltip,
    Legend,
    Filler
  );

  /**
   * @type {{
   *   business: any[],
   *   competitors: any[],
   *   businessName?: string,
   *   metric?: 'review_count' | 'rating' | 'instagram_followers' | 'instagram_posts'
   * }}
   */
  let { business = [], competitors = [], businessName = 'Your business', metric = 'review_count' } = $props();

  /** @type {HTMLCanvasElement | null} */
  let canvas = $state(null);
  /** @type {Chart | null} */
  let chart = null;

  // Backend serialises datetimes as naive UTC ISO without a trailing Z. The
  // dashboard's other Date-parsing helpers append 'Z' so the browser doesn't
  // treat them as local. Mirror that here.
  /** @param {string | null | undefined} value */
  function toUtcIso(value) {
    if (!value) return null;
    return /Z|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  }

  // Soft palette pulled from the existing tailwind tokens — competitor lines
  // need to be visually distinct from the user's own line without screaming.
  const COMPETITOR_PALETTE = [
    '#f59e0b', // attention-500
    '#fb7185', // action-400
    '#6366f1', // indigo-500
    '#0ea5e9', // sky-500
  ];

  function buildDatasets() {
    const yKey = metric;
    const businessPoints = (business ?? [])
      .filter((/** @type {any} */ p) => p[yKey] != null)
      .map((/** @type {any} */ p) => ({ x: toUtcIso(p.observed_at), y: p[yKey] }));

    /** @type {any[]} */
    const datasets = [
      {
        label: businessName,
        data: businessPoints,
        borderColor: '#10b981', // healthy-500
        backgroundColor: 'rgba(16, 185, 129, 0.12)',
        borderWidth: 2.5,
        pointRadius: 4,
        pointHoverRadius: 6,
        fill: false,
        tension: 0.3,
        spanGaps: true
      }
    ];

    (competitors ?? []).forEach((/** @type {any} */ comp, /** @type {number} */ idx) => {
      const color = COMPETITOR_PALETTE[idx % COMPETITOR_PALETTE.length];
      const pts = (comp.observations ?? [])
        .filter((/** @type {any} */ p) => p[yKey] != null)
        .map((/** @type {any} */ p) => ({ x: toUtcIso(p.observed_at), y: p[yKey] }));
      datasets.push({
        label: comp.name || `Competitor ${idx + 1}`,
        data: pts,
        borderColor: color,
        backgroundColor: color + '22',
        borderWidth: 2,
        borderDash: [6, 4],
        pointRadius: 3,
        pointHoverRadius: 5,
        fill: false,
        tension: 0.3,
        spanGaps: true
      });
    });

    return datasets;
  }

  function buildOptions() {
    const yLabel =
      metric === 'rating'
        ? 'Rating (1–5)'
        : metric === 'instagram_followers'
          ? 'Instagram followers'
          : metric === 'instagram_posts'
            ? 'Instagram posts'
            : 'Review count';
    const yMax = metric === 'rating' ? 5 : undefined;
    const yMin = metric === 'rating' ? 0 : 0;
    /** @type {any} */
    const opts = {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: 'nearest', intersect: false },
      plugins: {
        legend: {
          position: 'bottom',
          labels: { boxWidth: 12, boxHeight: 12, usePointStyle: true, padding: 16 }
        },
        tooltip: {
          callbacks: {
            label: (/** @type {any} */ ctx) => {
              const v = ctx.parsed.y;
              const label = ctx.dataset.label || '';
              if (metric === 'rating') return `${label}: ${v?.toFixed?.(1) ?? v} ★`;
              return `${label}: ${v}`;
            }
          }
        }
      },
      scales: {
        x: {
          type: 'timeseries',
          time: { tooltipFormat: 'PP' },
          ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 6 },
          grid: { display: false }
        },
        y: {
          beginAtZero: metric !== 'rating',
          min: yMin,
          max: yMax,
          title: { display: true, text: yLabel, color: '#6b7280' },
          ticks: { color: '#6b7280' },
          grid: { color: 'rgba(0,0,0,0.05)' }
        }
      }
    };
    return opts;
  }

  let renderError = $state(/** @type {string | null} */ (null));

  function renderChart() {
    if (!canvas) return;
    try {
      const datasets = buildDatasets();
      if (chart) {
        chart.data.datasets = datasets;
        chart.options = buildOptions();
        chart.update();
        return;
      }
      chart = new Chart(canvas, {
        type: 'line',
        data: { datasets },
        options: buildOptions()
      });
      renderError = null;
    } catch (err) {
      // Don't blow up the whole page if Chart.js chokes on bad data — fall
      // back to the friendly message overlay instead.
      renderError =
        err instanceof Error ? err.message : 'We couldn\'t draw your chart right now.';
    }
  }

  onMount(() => {
    renderChart();
  });

  // Re-render whenever inputs change (e.g. a competitor was just added and
  // the parent refetched). $effect runs in DOM-update order so canvas is
  // present.
  $effect(() => {
    void business;
    void competitors;
    void metric;
    if (chart) renderChart();
  });

  onDestroy(() => {
    chart?.destroy();
    chart = null;
  });

  // The "we'll start drawing your line" overlay should only appear when
  // the chart truly has nothing to draw — not just when the *primary*
  // business series is empty. The Market view, for instance, passes
  // additional user businesses through the competitors channel; if any
  // of those have observations the chart already has lines and the
  // overlay would just sit awkwardly behind the legend.
  const hasAnyPoint = $derived(
    (business ?? []).some((p) => p[metric] != null) ||
      (competitors ?? []).some((/** @type {any} */ c) =>
        (c.observations ?? []).some((/** @type {any} */ p) => p[metric] != null)
      )
  );
</script>

<div class="relative h-72 w-full sm:h-80">
  <canvas bind:this={canvas} aria-label="Rating and review-count trend over time"></canvas>
  {#if renderError}
    <div
      class="absolute inset-0 grid place-items-center rounded-2xl bg-canvas-soft/40 px-4 text-center text-sm text-canvas-muted"
    >
      <div>
        <p class="text-2xl">📈</p>
        <p class="mt-2 font-medium text-canvas-ink">
          We couldn't draw your chart right now.
        </p>
        <p class="mt-1 text-xs">Refresh the page to try again.</p>
      </div>
    </div>
  {:else if !hasAnyPoint}
    <div class="absolute inset-x-0 bottom-6 text-center text-xs text-canvas-muted">
      We'll start drawing your line after your next audit captures rating data.
    </div>
  {/if}
</div>
