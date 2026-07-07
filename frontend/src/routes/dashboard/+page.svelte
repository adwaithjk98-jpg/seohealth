<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';
  import { reduced } from '$lib/motion.js';

  import { authState, loadCurrentUser, greetingName } from '$lib/auth.svelte.js';
  import {
    trendArrow,
    trendTone,
    scoreTone,
    scoreLabel,
    severityLabel,
    severityTone,
    topOpenRecommendations,
    formatRelativeTime
  } from '$lib/dashboard.js';
  import UpgradeCallout from '$lib/components/UpgradeCallout.svelte';
  import WeeklyInsightsButton from '$lib/components/WeeklyInsightsButton.svelte';
  import { MAX } from '$lib/tiers.js';

  /** @type {{ data: { businesses: any[] | null, error: string | null, heroAudit: any | null } }} */
  let { data } = $props();

  const businesses = $derived(data?.businesses ?? []);
  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );
  // Total open recommendations across every business — drives the
  // "things worth a look" copy. Comes from the businesses listing payload
  // so we don't fan out an extra fetch on every dashboard render.
  const totalOpenInsights = $derived(
    businesses.reduce(
      (/** @type {number} */ acc, /** @type {any} */ b) =>
        acc + (b.open_recommendations_count ?? 0),
      0
    )
  );

  // --- Status-first hero (single-business users: every Free + Pro account).
  // The returning owner's first screen answers "am I fine, did anything
  // change, is there one thing worth doing" without another tap. The
  // heroAudit comes from +page.js; if that fetch failed we quietly fall
  // back to the business-card view below.
  const heroBiz = $derived(businesses.length === 1 ? businesses[0] : null);
  const heroAudit = $derived(data?.heroAudit ?? null);
  const heroSections = $derived(
    (heroAudit?.sections ?? []).filter((/** @type {any} */ s) => s.enabled !== false)
  );
  const heroTopMove = $derived(topOpenRecommendations(heroSections, 1)[0] ?? null);
  const heroSince = $derived(heroAudit?.since_last_check ?? null);
  const showHero = $derived(
    heroBiz != null &&
      (heroAudit != null || heroBiz.running_audit_id || heroBiz.latest_audit_id == null)
  );

  // One short "what changed" line for the hero. Null when there's no prior
  // audit to compare against (first week — stay quiet rather than dead).
  const heroChanges = $derived.by(() => {
    if (!heroSince?.prev_finished_at) return null;
    /** @type {string[]} */
    const parts = [];
    const n = heroSince.new?.length ?? 0;
    const c = heroSince.confirmed?.length ?? 0;
    const u = heroSince.unverified_done?.length ?? 0;
    if (c) parts.push(`${c} fix${c === 1 ? '' : 'es'} confirmed`);
    if (n) parts.push(`${n} new thing${n === 1 ? '' : 's'} to look at`);
    if (u) parts.push(`${u} marked done, not seen yet`);
    if (parts.length === 0) return 'Nothing new since your last check';
    return parts.join(' · ');
  });

  function heroMoveHref() {
    if (!heroTopMove || !heroAudit?.audit_id) return '/dashboard/insights';
    return `/audits/${heroAudit.audit_id}/dashboard/sections/${heroTopMove.section}?finding=${heroTopMove.id}`;
  }

  // First-audit kickoff straight from the hero — the old path bounced
  // through "/" which redirects signed-in users right back here.
  let startingAudit = $state(false);
  let startError = $state(/** @type {string | null} */ (null));
  async function handleStartFirstAudit() {
    if (!heroBiz || startingAudit) return;
    startingAudit = true;
    startError = null;
    try {
      const res = await fetch('/api/audits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ business_id: heroBiz.id })
      });
      if (res.status === 409) {
        const body = await res.json().catch(() => null);
        const runningId = body?.detail?.running_audit_id;
        if (runningId) {
          await goto(`/audits/${runningId}`);
          return;
        }
      }
      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(
          typeof body?.detail === 'string'
            ? body.detail
            : body?.detail?.message ?? `Request failed (${res.status})`
        );
      }
      const audit = await res.json();
      await goto(`/audits/${audit.audit_id}`);
    } catch (err) {
      startError = err instanceof Error ? err.message : 'Could not start your health check.';
      startingAudit = false;
    }
  }

  /** Time-aware greeting — the home should feel like it noticed you came back. */
  function timeGreeting() {
    const h = new Date().getHours();
    if (h < 5) return 'Welcome back';
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  }

  // Gate the "Add another business" CTA on the user's tier limits. The
  // server enforces this (402 from POST /api/businesses) — the UI just
  // avoids dangling the button when it can't be used.
  const subState = $derived(authState.user?.subscription_state ?? null);
  const businessLimit = $derived(subState?.limits?.businesses ?? 1);
  const atBusinessLimit = $derived(businesses.length >= businessLimit);
  // Over-cap can happen after a plan downgrade — the row still exists,
  // it just can't be audited the same way going forward. Surface that
  // honestly instead of saying "you're at the N-business limit" when
  // the user has clearly more than N.
  const overBusinessLimit = $derived(businesses.length > businessLimit);
  const tier = $derived(subState?.tier ?? authState.user?.plan ?? 'free');
  const isPaid = $derived(tier !== 'free');

  /**
   * Format a backend-provided naive-UTC ISO timestamp into a short, friendly
   * date label. Backend serialises Audit.finished_at as naive-UTC, so we
   * append 'Z' before parsing to keep `Date` from treating it as local time.
   * @param {string | null | undefined} value
   */
  function formatAuditDate(value) {
    if (!value) return null;
    const iso = /Z|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
  }

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user || data?.error === 'unauthenticated') {
      await goto('/login', { replaceState: true });
    }
  });

  const trendToneClass = {
    healthy: 'bg-healthy-50 text-healthy-700',
    attention: 'bg-attention-50 text-attention-700',
    action: 'bg-action-50 text-action-700',
    muted: 'bg-canvas-soft text-canvas-muted'
  };

  const gradeToneClass = {
    healthy: 'bg-healthy-50 text-healthy-700',
    attention: 'bg-attention-50 text-attention-700',
    action: 'bg-action-50 text-action-700',
    muted: 'bg-canvas-soft text-canvas-muted'
  };

  const severityToneClasses = {
    healthy: 'bg-healthy-50 text-healthy-700',
    attention: 'bg-attention-50 text-attention-700',
    action: 'bg-action-50 text-action-700',
    muted: 'bg-canvas-soft text-canvas-muted'
  };

  // Ring stroke colors mirror ScoreGauge so the two read as one system.
  const ringStroke = {
    healthy: '#4f8c5b',
    attention: '#c69423',
    action: '#d35a3f',
    muted: '#9a978d'
  };
  const ringTrack = {
    healthy: '#e3efe5',
    attention: '#faedc9',
    action: '#fbe3da',
    muted: '#ece9e1'
  };
</script>

<svelte:head><title>Home · SEO Health</title></svelte:head>

{#snippet scoreRing(/** @type {number | null} */ score, /** @type {number} */ size)}
  {@const tone = scoreTone(score)}
  {@const r = (size - 10) / 2}
  {@const c = 2 * Math.PI * r}
  {@const progress = score == null ? 0 : Math.max(0, Math.min(100, score)) / 100}
  <div class="relative shrink-0" style={`width:${size}px;height:${size}px`}>
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} aria-hidden="true">
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={ringTrack[tone]} stroke-width="9" />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={r}
        fill="none"
        stroke={ringStroke[tone]}
        stroke-width="9"
        stroke-linecap="round"
        stroke-dasharray={c}
        stroke-dashoffset={c * (1 - progress)}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
    </svg>
    <div class="absolute inset-0 grid place-items-center">
      <span class="text-2xl font-semibold tracking-tight text-canvas-ink">
        {score == null ? '—' : score}
      </span>
    </div>
  </div>
{/snippet}

<section class="space-y-6 sm:space-y-8">
  <header>
    <h1 class="text-2xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
      {timeGreeting()}{#if authState.user},
        <span class="text-healthy-600">{greetingName(authState.user)}</span>
      {/if}
    </h1>
    {#if showHero && heroBiz}
      <p class="mt-2 text-sm text-canvas-muted">
        Here's where <span class="font-medium text-canvas-ink">{heroBiz.name}</span> stands.
      </p>
    {:else if businesses.length > 1}
      <p class="mt-2 text-sm text-canvas-muted">
        {#if totalOpenInsights > 0}
          Across your {businesses.length} businesses: {totalOpenInsights}
          {totalOpenInsights === 1 ? 'thing' : 'things'} worth a look.
        {:else}
          All quiet across your {businesses.length} businesses.
        {/if}
      </p>
    {:else}
      <p class="mt-2 text-sm text-canvas-muted">
        Pick a business to see its latest health check, or add a new one.
      </p>
    {/if}
  </header>

  {#if errorMessage}
    <div
      class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700"
      in:fade={reduced({ duration: 220 })}
    >
      <p class="font-medium">We couldn't load your businesses right now.</p>
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
    <div
      class="card flex flex-col items-start gap-4 p-6 sm:p-8"
      in:fade={reduced({ duration: 260 })}
    >
      <p class="text-2xl">👋</p>
      <h2 class="text-lg font-semibold text-canvas-ink">No businesses yet</h2>
      <p class="text-sm text-canvas-muted">
        Add your first business and we'll quietly start checking on it — Google Maps,
        your website, Instagram, and how your name and number look across the web.
      </p>
      <a class="btn-primary w-full sm:w-auto" href="/">Add a business</a>
    </div>
  {:else if showHero && heroBiz}
    <!-- ═══ Single-business hero: the weekly loop's first screen. ═══ -->
    {#if heroBiz.running_audit_id}
      <a
        href={`/audits/${heroBiz.running_audit_id}`}
        class="card flex items-center gap-4 border-healthy-100 bg-gradient-to-br from-healthy-50/70 to-white p-5 transition hover:-translate-y-0.5 hover:shadow-md sm:p-6"
        in:fly={reduced({ y: 10, duration: 300, easing: quintOut })}
      >
        <span class="relative grid h-12 w-12 shrink-0 place-items-center" aria-hidden="true">
          <span class="absolute inset-0 animate-pulse rounded-full bg-healthy-200/50"></span>
          <span class="relative grid h-10 w-10 place-items-center rounded-full bg-white text-healthy-700 shadow-sm">
            <span class="inline-block h-2 w-2 animate-pulse rounded-full bg-healthy-500"></span>
          </span>
        </span>
        <div class="min-w-0 flex-1">
          <p class="text-base font-semibold tracking-tight text-canvas-ink">
            Health check in progress
          </p>
          <p class="mt-0.5 text-sm text-canvas-muted">
            We're looking at {heroBiz.name} right now — watch it live.
          </p>
        </div>
        <span class="text-canvas-muted" aria-hidden="true">→</span>
      </a>
    {:else if heroAudit}
      <a
        href={`/businesses/${heroBiz.id}`}
        class="card group block p-5 transition hover:-translate-y-0.5 hover:border-healthy-200 hover:shadow-md sm:p-6"
        in:fly={reduced({ y: 10, duration: 300, easing: quintOut })}
        data-sveltekit-preload-data="tap"
      >
        <div class="flex items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-base font-semibold tracking-tight text-canvas-ink">
              {heroBiz.name}
            </p>
            <p class="text-xs text-canvas-muted">
              {heroBiz.city}{heroBiz.country ? ` · ${heroBiz.country}` : ''}
              · checked {formatRelativeTime(heroAudit.finished_at)}
            </p>
          </div>
          {#if trendArrow(heroAudit.overall_trend)}
            <span
              class={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${trendToneClass[trendTone(heroAudit.overall_trend)]}`}
            >
              {trendArrow(heroAudit.overall_trend)}
              {#if heroAudit.previous_overall_score != null && heroAudit.overall_score != null && heroAudit.overall_score !== heroAudit.previous_overall_score}
                {Math.abs(heroAudit.overall_score - heroAudit.previous_overall_score)}
              {:else}
                Steady
              {/if}
            </span>
          {/if}
        </div>

        <div class="mt-4 flex items-center gap-4">
          {@render scoreRing(heroAudit.overall_score, 84)}
          <div class="min-w-0">
            <p class="text-sm font-medium text-canvas-ink">
              {scoreLabel(heroAudit.overall_score)}
            </p>
            {#if heroChanges}
              <p class="mt-1 text-xs text-canvas-muted">{heroChanges}</p>
            {:else}
              <p class="mt-1 text-xs text-canvas-muted">
                We'll compare against this check from next time.
              </p>
            {/if}
          </div>
        </div>

        {#if heroSections.length > 0}
          <div class="mt-4 flex flex-wrap gap-1.5" aria-label="Pillar scores">
            {#each heroSections as s (s.section)}
              <span
                class={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${gradeToneClass[scoreTone(s.score)]}`}
                title={`${s.label}: ${s.score ?? '—'}/100`}
              >
                <span aria-hidden="true">{s.emoji}</span>
                {s.score ?? '—'}
              </span>
            {/each}
          </div>
        {/if}

        <p class="mt-4 flex items-center justify-end gap-1 text-sm font-medium text-healthy-700">
          See the full health check
          <span class="transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden="true">→</span>
        </p>
      </a>

      {#if heroTopMove}
        <a
          href={heroMoveHref()}
          class="card group block p-5 transition hover:-translate-y-0.5 hover:border-healthy-200 hover:shadow-md"
          in:fly={reduced({ y: 10, delay: 60, duration: 300, easing: quintOut })}
        >
          <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
            Your one move this week
          </p>
          <div class="mt-2 flex flex-wrap items-center gap-2">
            <span
              class={`rounded-full px-2 py-0.5 text-xs font-medium ${severityToneClasses[severityTone(heroTopMove.severity)]}`}
            >
              {severityLabel(heroTopMove.severity)}
            </span>
            <span class="text-xs text-canvas-muted">
              {heroTopMove.sectionEmoji} {heroTopMove.sectionLabel}
            </span>
            {#if heroTopMove.estimated_time}
              <span class="text-xs text-canvas-muted">· {heroTopMove.estimated_time}</span>
            {/if}
          </div>
          <p class="mt-1.5 font-medium text-canvas-ink">{heroTopMove.title}</p>
          <p class="mt-2 text-sm font-medium text-healthy-700">
            Open this fix
            <span class="inline-block transition-transform duration-200 group-hover:translate-x-0.5" aria-hidden="true">→</span>
          </p>
        </a>
      {:else}
        <div
          class="card border border-healthy-100 bg-healthy-50/60 p-5 text-center"
          in:fade={reduced({ duration: 300 })}
        >
          <p class="font-medium text-healthy-700">You're all caught up. 🎉</p>
          <p class="mt-1 text-sm text-canvas-muted">
            No open recommendations — we'll keep quietly checking and let you know when
            something needs attention.
          </p>
        </div>
      {/if}

      <div class="flex flex-wrap items-center gap-3">
        <WeeklyInsightsButton {businesses} />
        {#if totalOpenInsights > 0}
          <a
            href="/dashboard/insights"
            data-sveltekit-preload-data="tap"
            class="btn-ghost text-sm"
          >
            All {totalOpenInsights} things worth a look →
          </a>
        {/if}
      </div>
    {:else}
      <!-- Single business, no audit yet: the first check starts right here.
           (The old CTA sent people to "/", which bounces signed-in users
           straight back to this page.) -->
      <div
        class="card flex flex-col items-start gap-4 p-6 sm:p-8"
        in:fly={reduced({ y: 10, duration: 300, easing: quintOut })}
      >
        <div class="flex items-center gap-4">
          {@render scoreRing(null, 72)}
          <div>
            <h2 class="text-lg font-semibold text-canvas-ink">{heroBiz.name}</h2>
            <p class="text-sm text-canvas-muted">
              No health check yet — the first one takes about 5 minutes, and we'll show you
              every step as it runs.
            </p>
          </div>
        </div>
        {#if startError}
          <p class="rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700" role="alert">
            {startError}
          </p>
        {/if}
        <button
          type="button"
          class="btn-primary w-full sm:w-auto"
          onclick={handleStartFirstAudit}
          disabled={startingAudit}
        >
          {#if startingAudit}
            <span class="inline-flex items-center justify-center gap-2">
              <span
                class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                aria-hidden="true"
              ></span>
              Starting your health check…
            </span>
          {:else}
            Run my first health check
          {/if}
        </button>
      </div>
    {/if}

    {#if !isPaid}
      <!-- Quiet, below the content it upsells — never above the status. -->
      <UpgradeCallout
        eyebrow="Pro"
        title="Let us watch for you"
        body="Pro re-checks on a schedule, tracks competitors, and emails you the moment your score moves."
        cta="See plans"
      />
    {/if}
  {:else}
    <!-- ═══ Multi-business grid (Max), or single-business fallback when the
         hero's audit fetch failed. ═══ -->
    <div>
      <WeeklyInsightsButton {businesses} />
    </div>

    <a
      href="/dashboard/insights"
      data-sveltekit-preload-data="tap"
      class="group relative flex flex-col gap-5 overflow-hidden rounded-2xl border border-healthy-100 bg-gradient-to-br from-healthy-50 via-attention-50/40 to-white p-6 shadow-soft transition-all duration-200 hover:-translate-y-0.5 hover:border-healthy-200 hover:shadow-md sm:p-8"
    >
      <div class="flex items-start justify-between gap-3">
        <p
          class="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-healthy-700"
        >
          <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
          Your insights
        </p>
        <span class="relative grid h-12 w-12 shrink-0 place-items-center" aria-hidden="true">
          <span class="absolute inset-0 animate-pulse rounded-full bg-healthy-200/40"></span>
          <span
            class="relative grid h-10 w-10 place-items-center rounded-full bg-white text-healthy-700 shadow-sm transition-transform duration-300 group-hover:scale-110"
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="h-5 w-5"
            >
              <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1" />
              <circle cx="12" cy="12" r="3.2" />
            </svg>
          </span>
        </span>
      </div>

      {#if totalOpenInsights === 0}
        <div class="space-y-1">
          <p class="text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
            All caught up
          </p>
          <p class="text-sm text-canvas-muted">
            Tap to peek — we'll let you know the moment something new lands.
          </p>
        </div>
      {:else}
        <div class="space-y-1">
          <p class="flex items-baseline gap-2 text-canvas-ink">
            <span class="text-5xl font-semibold tracking-tight text-healthy-700 sm:text-6xl">
              {totalOpenInsights}
            </span>
            <span class="text-base font-medium sm:text-lg">
              {totalOpenInsights === 1 ? 'thing' : 'things'} worth a look
            </span>
          </p>
          <p class="text-sm text-canvas-muted">
            Across your {businesses.length}
            {businesses.length === 1 ? 'business' : 'businesses'} · tap to dive in
          </p>
        </div>
      {/if}

      <span
        class="self-end text-sm font-medium text-healthy-700 transition-transform duration-200 group-hover:translate-x-1"
        aria-hidden="true"
      >
        View insights →
      </span>
    </a>

    <div class="grid gap-4 sm:grid-cols-2">
      {#each businesses as biz, i (biz.id)}
        {@const tone = scoreTone(biz.latest_score)}
        {@const arrow = trendArrow(biz.latest_trend)}
        <a
          href={biz.running_audit_id
            ? `/audits/${biz.running_audit_id}`
            : `/businesses/${biz.id}`}
          class="card flex flex-col gap-3 p-5 transition hover:border-canvas-muted/30 hover:shadow-soft"
          in:fly={reduced({ y: 12, delay: 60 * i, duration: 320, easing: quintOut })}
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="truncate text-base font-semibold text-canvas-ink">{biz.name}</p>
              <p class="text-xs text-canvas-muted">{biz.city} · {biz.country}</p>
            </div>
            {#if biz.latest_score != null}
              <span
                class={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${gradeToneClass[tone]}`}
                title={`Score ${biz.latest_score}/100`}
              >
                {biz.latest_score}
                {#if arrow}
                  <span class={`text-[10px] ${trendToneClass[trendTone(biz.latest_trend)]} rounded-full px-1`}>
                    {arrow}
                  </span>
                {/if}
              </span>
            {/if}
          </div>

          {#if biz.running_audit_id}
            <p class="inline-flex items-center gap-1.5 text-xs font-medium text-healthy-700">
              <span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-healthy-500"></span>
              Health check in progress · watch it live →
            </p>
          {:else if biz.latest_audit_finished_at}
            <p class="text-xs text-canvas-muted">
              Last checked {formatRelativeTime(biz.latest_audit_finished_at)}
            </p>
            {#if isPaid && biz.next_auto_audit_at}
              <p class="text-xs text-canvas-muted">
                Next auto-audit scheduled for
                <span class="font-medium text-canvas-ink">
                  {formatAuditDate(biz.next_auto_audit_at)}
                </span>
              </p>
            {/if}
            <span class="mt-auto inline-flex items-center gap-1 text-xs font-medium text-healthy-700">
              See latest health check →
            </span>
          {:else}
            <p class="text-xs text-canvas-muted">No health check yet.</p>
            {#if isPaid && biz.next_auto_audit_at}
              <p class="text-xs text-canvas-muted">
                Next auto-audit scheduled for
                <span class="font-medium text-canvas-ink">
                  {formatAuditDate(biz.next_auto_audit_at)}
                </span>
              </p>
            {/if}
            <span class="mt-auto inline-flex items-center gap-1 text-xs font-medium text-healthy-700">
              Start a health check →
            </span>
          {/if}
        </a>
      {/each}
    </div>
  {/if}

  {#if !errorMessage && businesses.length > 0}
    <div class="flex flex-wrap items-center gap-3">
      {#if !atBusinessLimit}
        <a class="btn-ghost w-full sm:w-auto" href="/?add=1">+ Add another business</a>
      {:else if tier === 'free'}
        <!-- The Pro pitch already sits above for free users; the cap note
             here stays factual so the row doesn't double-sell. -->
        <p class="text-xs text-canvas-muted">
          Free tracks one business. Paid plans add auto-audits and competitor tracking.
        </p>
      {:else if overBusinessLimit}
        <p class="text-xs text-canvas-muted">
          You're tracking {businesses.length} businesses but your plan covers {businessLimit}.
          We'll keep everything visible — archive one to add a new business going forward.
        </p>
      {:else}
        <!-- Pro user at the 1-business cap. Rare edge case, kept low-key: the
             Max tone is muted + ghost, deliberately quieter than Pro nudges. -->
        <UpgradeCallout
          tone="max"
          title="Want more than Pro?"
          body={`Max steps up to twice-weekly auto-audits & competitor refresh, ${MAX.competitors} competitors, and up to ${MAX.businesses} businesses.`}
          cta="See Max"
        />
      {/if}
    </div>
  {/if}
</section>
