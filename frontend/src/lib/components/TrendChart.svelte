<script>
  // Hand-rolled SVG trend chart — replaces the Chart.js line chart.
  //
  // Design (dataviz "emphasis" form): the user's line is the point, the
  // competitors are context. One sage line with an area wash + white-ringed
  // dots; competitor lines thinner in muted, fixed-slot colors. Identity is
  // carried by direct end-labels in a right gutter (with leader lines when
  // labels shove apart) plus a quiet toggleable legend — never by color
  // alone. Y-axis fits the data instead of forcing zero; date ticks are
  // deduped. A crosshair tooltip reads every series at the nearest date.
  //
  // The props contract is unchanged from the Chart.js version so both
  // callers (market page, competitor deep dive) keep working.

  /**
   * @typedef {{ observed_at?: string | null } & Record<string, any>} Observation
   * @typedef {{ competitor_id?: number | string, name?: string, color?: string, observations?: Observation[] }} CompetitorSeries
   */

  /**
   * @type {{
   *   business: Observation[],
   *   competitors: CompetitorSeries[],
   *   businessName?: string,
   *   metric?: 'review_count' | 'rating' | 'instagram_followers' | 'instagram_posts',
   *   showLegend?: boolean
   * }}
   */
  let {
    business = [],
    competitors = [],
    businessName = 'Your business',
    metric = 'review_count',
    // Deprecated / no-op: series identity now lives in the on-chart
    // end-labels, so there is no separate legend row to toggle. Kept in the
    // props so existing callers don't break.
    showLegend = true
  } = $props();

  // ---- palette (validated: dataviz six checks on the white card surface) --
  // Emphasis sage is healthy-500 nudged just over the chroma floor so it
  // doesn't read as gray in CVD simulation; competitor slots are fixed-order
  // and assigned by entity index, never re-cycled when series hide.
  const EMPHASIS = '#42945b';
  const SLOTS = ['#a3771b', '#6366f1', '#d35a3f', '#0284c7'];
  const GRID = '#eceae3'; // one step off the white card
  const INK = '#2b2a26';
  const MUTED = '#6b6960';

  // ---- layout constants -------------------------------------------------
  // Taller now that identity lives entirely in the on-chart end-labels (no
  // legend row below eating vertical space).
  const H = 300; // total SVG height, x-axis band included
  const M_TOP = 14;
  const M_BOTTOM = 26;
  const LABEL_GAP = 15; // min vertical space between end labels

  let width = $state(0);

  // Backend serialises datetimes as naive UTC ISO without a trailing Z.
  /** @param {string | null | undefined} value */
  function toUtcIso(value) {
    if (!value) return null;
    return /Z|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
  }

  // Clear any pinned/hovered readout when the metric (or comparison target)
  // changes — the old snap index no longer means the same thing.
  $effect(() => {
    void metric;
    void businessName;
    pinnedIdx = null;
    hoverIdx = null;
  });

  /** All series, colors assigned by entity position (stable under hiding). */
  const allSeries = $derived.by(() => {
    /** @type {Array<{ id: string, name: string, color: string, emphasis: boolean, points: Array<{ t: number, y: number }> }>} */
    const out = [];
    const toPoints = (/** @type {Observation[]} */ obs) =>
      (obs ?? [])
        .map((p) => {
          const iso = toUtcIso(p.observed_at);
          const y = p[metric];
          return iso != null && y != null ? { t: Date.parse(iso), y: Number(y) } : null;
        })
        .filter((/** @type {any} */ p) => p && Number.isFinite(p.t) && Number.isFinite(p.y))
        .sort((/** @type {any} */ a, /** @type {any} */ b) => a.t - b.t);
    out.push({
      id: 'you',
      name: businessName,
      color: EMPHASIS,
      emphasis: true,
      points: /** @type {any} */ (toPoints(business))
    });
    (competitors ?? []).forEach((comp, idx) => {
      out.push({
        id: `c-${comp.competitor_id ?? idx}`,
        name: comp.name || `Competitor ${idx + 1}`,
        color: comp.color || SLOTS[idx % SLOTS.length],
        emphasis: false,
        points: /** @type {any} */ (toPoints(comp.observations ?? []))
      });
    });
    return out;
  });

  const visible = $derived(allSeries.filter((s) => s.points.length > 0));
  const hasAnyPoint = $derived(allSeries.some((s) => s.points.length > 0));

  // ---- value formatting ---------------------------------------------------
  /** @param {number} v */
  function fmtValue(v) {
    if (metric === 'rating') return v.toFixed(1) + ' ★';
    if (v >= 10000) return Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(v);
    return Math.round(v).toLocaleString('en');
  }

  const fmtDay = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric' });
  const fmtDayYear = new Intl.DateTimeFormat('en', { month: 'short', day: 'numeric', year: 'numeric' });

  // ---- scales -------------------------------------------------------------
  const xDomain = $derived.by(() => {
    const ts = visible.flatMap((s) => s.points.map((p) => p.t));
    if (ts.length === 0) return null;
    let lo = Math.min(...ts);
    let hi = Math.max(...ts);
    if (lo === hi) {
      const D = 3 * 86400_000;
      lo -= D;
      hi += D;
    }
    return { lo, hi };
  });

  /** Fitted y-domain with padded, niced bounds + 3 clean ticks. */
  const yScaleInfo = $derived.by(() => {
    const ys = visible.flatMap((s) => s.points.map((p) => p.y));
    if (ys.length === 0) return null;
    let lo = Math.min(...ys);
    let hi = Math.max(...ys);
    if (lo === hi) {
      const pad = Math.max(Math.abs(lo) * 0.1, metric === 'rating' ? 0.2 : 1);
      lo -= pad;
      hi += pad;
    } else {
      const pad = (hi - lo) * 0.12;
      lo -= pad;
      hi += pad;
    }
    if (metric === 'rating') {
      lo = Math.max(0, lo);
      hi = Math.min(5.05, hi);
    } else {
      lo = Math.max(0, lo);
    }
    // Nice step: the smallest 1/2/5 × 10^k step that yields ≤ 6 ticks, so a
    // tall-but-narrow value range doesn't get flattened onto a coarse axis.
    const span = hi - lo;
    const mag = Math.pow(10, Math.floor(Math.log10(span / 6)));
    const candidates = [1, 2, 5, 10, 20, 50].map((m) => m * mag);
    const step =
      candidates.find((s) => Math.ceil(hi / s) - Math.floor(lo / s) + 1 <= 6) ??
      candidates[candidates.length - 1];
    const tickLo = Math.max(0, Math.floor(lo / step) * step);
    let tickHi = Math.ceil(hi / step) * step;
    if (metric === 'rating') tickHi = Math.min(tickHi, 5);
    /** @type {number[]} */
    const ticks = [];
    for (let v = tickLo; v <= tickHi + step / 2; v += step) ticks.push(v);
    return { lo: tickLo, hi: tickHi, ticks: ticks.filter((v) => v <= tickHi + step / 2) };
  });

  /** @param {string} name */
  function shortName(name) {
    return name.length > 13 ? name.slice(0, 12).trimEnd() + '…' : name;
  }

  // Right gutter sized to the longest visible label (capped for phones):
  // 15px label x-offset past the plot edge + ~6.1px/char + breathing room.
  const gutter = $derived.by(() => {
    if (visible.length === 0) return 8;
    const longest = Math.max(...visible.map((s) => shortName(s.name).length));
    return Math.min(width < 420 ? 96 : 116, 21 + longest * 6.1);
  });

  const mLeft = $derived.by(() => {
    if (!yScaleInfo) return 30;
    const longest = Math.max(...yScaleInfo.ticks.map((t) => fmtValue(t).length));
    return Math.max(26, 10 + longest * 6.4);
  });

  const plotW = $derived(Math.max(10, width - mLeft - gutter));
  const plotH = H - M_TOP - M_BOTTOM;

  const x = $derived((/** @type {number} */ t) =>
    xDomain ? mLeft + ((t - xDomain.lo) / (xDomain.hi - xDomain.lo)) * plotW : mLeft
  );
  const y = $derived((/** @type {number} */ v) =>
    yScaleInfo
      ? M_TOP + plotH - ((v - yScaleInfo.lo) / (yScaleInfo.hi - yScaleInfo.lo || 1)) * plotH
      : M_TOP + plotH
  );

  // ---- geometry -----------------------------------------------------------
  /** @param {Array<{ t: number, y: number }>} pts */
  function linePath(pts) {
    return pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.t).toFixed(1)},${y(p.y).toFixed(1)}`).join(' ');
  }

  /** Area wash under the emphasis line only. */
  /** @param {Array<{ t: number, y: number }>} pts */
  function areaPath(pts) {
    if (pts.length < 2) return '';
    const base = (M_TOP + plotH).toFixed(1);
    return (
      linePath(pts) +
      ` L${x(pts[pts.length - 1].t).toFixed(1)},${base} L${x(pts[0].t).toFixed(1)},${base} Z`
    );
  }

  // Direct end labels: greedy vertical de-collision in the gutter, leader
  // lines when a label had to move off its line-end.
  const endLabels = $derived.by(() => {
    const items = visible
      .map((s) => {
        const last = s.points[s.points.length - 1];
        return { s, lineY: y(last.y), lineX: x(last.t) };
      })
      .sort((a, b) => a.lineY - b.lineY);
    let prev = -Infinity;
    for (const it of items) {
      /** @type {any} */ (it).labelY = Math.max(it.lineY, prev + LABEL_GAP);
      prev = /** @type {any} */ (it).labelY;
    }
    // If the stack overflowed the plot bottom, shift the tail back up.
    const bottom = M_TOP + plotH;
    const overflow = prev - bottom;
    if (overflow > 0) {
      for (let i = items.length - 1, room = overflow; i >= 0 && room > 0; i--) {
        const it = /** @type {any} */ (items[i]);
        const minY = i === 0 ? M_TOP + 4 : /** @type {any} */ (items[i - 1]).labelY + LABEL_GAP;
        const lift = Math.min(room, it.labelY - minY);
        it.labelY -= lift;
        room -= lift;
      }
    }
    return /** @type {Array<{ s: (typeof visible)[number], lineY: number, lineX: number, labelY: number }>} */ (
      /** @type {any} */ (items)
    );
  });

  // ---- x ticks: unique days, ≤ 4, always first + last ----------------------
  const xTicks = $derived.by(() => {
    if (!xDomain) return [];
    const seen = new Set();
    /** @type {number[]} */
    const days = [];
    for (const s of visible) {
      for (const p of s.points) {
        const key = new Date(p.t).toISOString().slice(0, 10);
        if (!seen.has(key)) {
          seen.add(key);
          days.push(p.t);
        }
      }
    }
    days.sort((a, b) => a - b);
    const n = days.length;
    /** @type {number[]} */
    let picked;
    if (n <= 4) {
      picked = days;
    } else {
      picked = [days[0]];
      for (const f of [1 / 3, 2 / 3]) {
        const cand = days[Math.round(f * (n - 1))];
        if (!picked.includes(cand)) picked.push(cand);
      }
      picked.push(days[n - 1]);
    }
    // Enforce pixel spacing so close dates ("Jun 7", "Jun 8") never print on
    // top of each other. Last tick wins over a crowding middle one.
    const MIN_PX = 48;
    /** @type {number[]} */
    const spaced = [];
    for (const t of picked) {
      if (spaced.length === 0 || x(t) - x(spaced[spaced.length - 1]) >= MIN_PX) {
        spaced.push(t);
      } else if (t === picked[picked.length - 1] && spaced.length > 1) {
        spaced[spaced.length - 1] = t;
      }
    }
    return spaced;
  });

  // ---- crosshair + tooltip --------------------------------------------------
  /** Sorted unique timestamps across visible series (crosshair snap grid). */
  const hoverXs = $derived.by(() => {
    const set = new Set(visible.flatMap((s) => s.points.map((p) => p.t)));
    return [...set].sort((a, b) => a - b);
  });

  // Two channels: a tap PINS the readout (persists — the primary path on
  // touch, where there is no hover) and a mouse-hover PREVIEWS it
  // transiently. The pin wins when both are set.
  /** @type {number | null} */
  let pinnedIdx = $state(null);
  /** @type {number | null} */
  let hoverIdx = $state(null);
  const activeIdx = $derived(pinnedIdx ?? hoverIdx);

  // Dismiss a pinned readout by tapping anywhere off the chart. onTap
  // stops propagation, so in-chart taps never reach this listener.
  $effect(() => {
    if (pinnedIdx == null) return;
    const close = () => (pinnedIdx = null);
    document.addEventListener('pointerdown', close);
    return () => document.removeEventListener('pointerdown', close);
  });

  const hover = $derived.by(() => {
    if (activeIdx == null || hoverXs.length === 0) return null;
    const t = hoverXs[Math.max(0, Math.min(activeIdx, hoverXs.length - 1))];
    const DAY = 86400_000;
    const rows = visible
      .map((s) => {
        // nearest observation within half a day of the crosshair date
        let best = null;
        for (const p of s.points) {
          if (Math.abs(p.t - t) < DAY / 2 && (!best || Math.abs(p.t - t) < Math.abs(best.t - t)))
            best = p;
        }
        return best ? { s, value: best.y } : null;
      })
      .filter((r) => r != null)
      .sort((a, b) => /** @type {any} */ (b).value - /** @type {any} */ (a).value);
    if (rows.length === 0) return null;
    const sameYear = new Date(t).getFullYear() === new Date().getFullYear();
    return {
      t,
      px: x(t),
      label: (sameYear ? fmtDay : fmtDayYear).format(t),
      rows: /** @type {Array<{ s: (typeof visible)[number], value: number }>} */ (/** @type {any} */ (rows))
    };
  });

  /** Nearest snap-grid index to the pointer's x. @param {PointerEvent} e */
  function nearestIdx(e) {
    const rect = /** @type {SVGSVGElement} */ (e.currentTarget).getBoundingClientRect();
    const px = e.clientX - rect.left;
    let best = 0;
    let bestD = Infinity;
    hoverXs.forEach((t, i) => {
      const d = Math.abs(x(t) - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    return best;
  }

  /** Tap/click: pin the readout (toggle off if the same point is tapped). */
  /** @param {PointerEvent} e */
  function onTap(e) {
    if (hoverXs.length === 0) return;
    e.stopPropagation(); // keep the outside-tap-to-dismiss listener from firing
    const idx = nearestIdx(e);
    pinnedIdx = pinnedIdx === idx ? null : idx;
    hoverIdx = null;
  }

  /** Mouse move: transient preview. While dragging (pressed) scrub the pin. */
  /** @param {PointerEvent} e */
  function onMove(e) {
    if (hoverXs.length === 0) return;
    const idx = nearestIdx(e);
    if (pinnedIdx != null && (e.buttons > 0 || e.pressure > 0)) pinnedIdx = idx;
    else hoverIdx = idx;
  }

  /** @param {KeyboardEvent} e */
  function onKey(e) {
    if (hoverXs.length === 0) return;
    if (e.key === 'ArrowRight') {
      pinnedIdx = pinnedIdx == null ? hoverXs.length - 1 : Math.min(pinnedIdx + 1, hoverXs.length - 1);
      e.preventDefault();
    } else if (e.key === 'ArrowLeft') {
      pinnedIdx = pinnedIdx == null ? 0 : Math.max(pinnedIdx - 1, 0);
      e.preventDefault();
    } else if (e.key === 'Escape') {
      pinnedIdx = null;
      hoverIdx = null;
    }
  }

  // Tooltip stays inside the card: clamp horizontally around the crosshair.
  const tooltipStyle = $derived.by(() => {
    if (!hover) return '';
    const w = 168;
    const left = Math.max(4, Math.min(hover.px - w / 2, width - w - 4));
    return `left:${left}px; top:0px; width:${w}px;`;
  });

  const metricNoun = $derived(
    metric === 'rating'
      ? 'rating'
      : metric === 'review_count'
        ? 'review-count'
        : metric === 'instagram_followers'
          ? 'Instagram-follower'
          : 'Instagram-post'
  );

  const ariaSummary = $derived.by(() => {
    if (!hasAnyPoint) return `No ${metricNoun} data charted yet.`;
    const names = visible.map((s) => s.name).join(', ');
    return `Trend of ${metricNoun.replace('-', ' ')} over time for ${names}. Use left and right arrow keys to read values.`;
  });
</script>

<div class="relative w-full" bind:clientWidth={width}>
  {#if width > 0}
    <!-- The svg IS an interactive widget (crosshair via pointer, arrow-key
         reading, Escape to dismiss) — Svelte's a11y checker doesn't credit
         role="application" on svg, so these two are false positives. -->
    <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
    <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
    <svg
      {width}
      height={H}
      class="block touch-pan-y select-none focus:outline-none focus-visible:ring-2 focus-visible:ring-healthy-300"
      role="application"
      aria-roledescription="interactive trend chart"
      aria-label={ariaSummary}
      tabindex="0"
      onpointermove={onMove}
      onpointerdown={onTap}
      onpointerleave={() => (hoverIdx = null)}
      onkeydown={onKey}
      onblur={() => (hoverIdx = null)}
    >
      {#if yScaleInfo && xDomain}
        <!-- recessive grid: solid hairlines, one step off the surface -->
        {#each yScaleInfo.ticks as tick (tick)}
          <line x1={mLeft} x2={mLeft + plotW} y1={y(tick)} y2={y(tick)} stroke={GRID} stroke-width="1" />
          <text
            x={mLeft - 6}
            y={y(tick) + 3.5}
            text-anchor="end"
            font-size="10.5"
            fill={MUTED}
            style="font-variant-numeric: tabular-nums;"
          >
            {fmtValue(tick)}
          </text>
        {/each}

        {#each xTicks as t (t)}
          <text x={x(t)} y={H - 8} text-anchor="middle" font-size="10.5" fill={MUTED}>
            {fmtDay.format(t)}
          </text>
        {/each}

        <!-- context lines first, emphasis line on top -->
        {#each visible.filter((s) => !s.emphasis) as s (s.id)}
          <path d={linePath(s.points)} fill="none" stroke={s.color} stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.75" pathLength="1" class="tc-draw" />
        {/each}

        {#each visible.filter((s) => s.emphasis) as s (s.id)}
          {#if s.points.length >= 2}
            <!-- group carries the entry fade so the wash keeps its 8% opacity -->
            <g class="tc-fade">
              <path d={areaPath(s.points)} fill={EMPHASIS} opacity="0.08" />
            </g>
          {/if}
          <path d={linePath(s.points)} fill="none" stroke={s.color} stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" pathLength="1" class="tc-draw" />
        {/each}

        <!-- crosshair under the dots -->
        {#if hover}
          <line x1={hover.px} x2={hover.px} y1={M_TOP} y2={M_TOP + plotH} stroke={INK} stroke-width="1" opacity="0.18" />
        {/if}

        <!-- dots: sparse observations ARE the data; 2px surface ring -->
        {#each visible as s (s.id)}
          {#each s.points as p, pi (pi)}
            <circle
              cx={x(p.t)}
              cy={y(p.y)}
              r={s.emphasis ? 4 : 3}
              fill={s.color}
              stroke="#ffffff"
              stroke-width="2"
              class="tc-fade"
            />
          {/each}
        {/each}

        <!-- direct end labels in the gutter, leaders when displaced -->
        {#each endLabels as item (item.s.id)}
          {#if Math.abs(item.labelY - item.lineY) > 6}
            <path
              d={`M${item.lineX + 5},${item.lineY} L${mLeft + plotW + 8},${item.labelY} L${mLeft + plotW + 12},${item.labelY}`}
              fill="none"
              stroke={item.s.color}
              stroke-width="1"
              opacity="0.4"
            />
          {:else}
            <line x1={item.lineX + 5} x2={mLeft + plotW + 12} y1={item.lineY} y2={item.labelY} stroke={item.s.color} stroke-width="1" opacity="0.4" />
          {/if}
          <text
            x={mLeft + plotW + 15}
            y={item.labelY + 3.5}
            font-size="11"
            font-weight={item.s.emphasis ? 600 : 500}
            fill={item.s.emphasis ? INK : MUTED}
          >
            {shortName(item.s.name)}
          </text>
        {/each}
      {/if}
    </svg>

    <!-- tooltip: values lead, names follow; line-keys carry identity -->
    {#if hover}
      <div
        class="pointer-events-none absolute z-10 rounded-xl border border-canvas-soft bg-white/95 px-3 py-2 shadow-soft backdrop-blur-sm"
        style={tooltipStyle}
      >
        <p class="text-[10px] font-medium uppercase tracking-wide text-canvas-muted">{hover.label}</p>
        <ul class="mt-1 space-y-0.5">
          {#each hover.rows as row (row.s.id)}
            <li class="flex items-center gap-1.5 text-xs">
              <span class="inline-block h-0.5 w-3 shrink-0 rounded-full" style={`background:${row.s.color}`} aria-hidden="true"></span>
              <span class="font-semibold text-canvas-ink" style="font-variant-numeric: tabular-nums;">{fmtValue(row.value)}</span>
              <span class="truncate text-canvas-muted">{row.s.name}</span>
            </li>
          {/each}
        </ul>
      </div>
    {/if}

    {#if !hasAnyPoint}
      <div class="pointer-events-none absolute inset-0 grid place-items-center px-6 text-center">
        <p class="max-w-xs rounded-2xl bg-canvas/90 px-3 py-2 text-xs text-canvas-muted shadow-sm backdrop-blur">
          We'll start drawing this line after the next weekly refresh captures
          {metricNoun} data.
        </p>
      </div>
    {/if}
  {:else}
    <div style={`height:${H}px`}></div>
  {/if}
</div>

<style>
  @media (prefers-reduced-motion: no-preference) {
    .tc-draw {
      stroke-dasharray: 1;
      stroke-dashoffset: 1;
      animation: tc-draw 0.7s ease-out forwards;
    }
    .tc-fade {
      opacity: 0;
      animation: tc-fade 0.4s ease-out 0.45s forwards;
    }
  }
  @keyframes tc-draw {
    to {
      stroke-dashoffset: 0;
    }
  }
  @keyframes tc-fade {
    to {
      opacity: 1;
    }
  }
</style>
