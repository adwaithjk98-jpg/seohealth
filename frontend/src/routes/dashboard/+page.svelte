<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser, greetingName } from '$lib/auth.svelte.js';
  import { trendArrow, trendTone, scoreTone, formatRelativeTime } from '$lib/dashboard.js';
  import Skeleton from '$lib/components/Skeleton.svelte';

  /** @type {{ data: { businesses: any[] | null, error: string | null } }} */
  let { data } = $props();

  const businesses = $derived(data?.businesses ?? []);
  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );
  // Total open recommendations across every business — drives the
  // "View all insights" pull-card copy. Comes from the businesses
  // listing payload so we don't fan out an extra fetch on every
  // dashboard render.
  const totalOpenInsights = $derived(
    businesses.reduce(
      (/** @type {number} */ acc, /** @type {any} */ b) =>
        acc + (b.open_recommendations_count ?? 0),
      0
    )
  );

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
</script>

<section class="space-y-8">
  <header>
    <p
      class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
    >
      <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
      Your businesses
    </p>
    <h1 class="mt-3 text-2xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
      Welcome back{#if authState.user},
        <span class="text-healthy-600">{greetingName(authState.user)}</span>
      {/if}
    </h1>
    <p class="mt-2 text-sm text-canvas-muted">
      Pick a business to see its latest health check, or add a new one.
    </p>
  </header>

  {#if !isPaid && businesses.length > 0}
    <div
      class="card flex flex-col gap-3 border border-attention-100 bg-attention-50/70 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between"
    >
      <div class="text-sm text-canvas-ink">
        <p class="font-medium">Upgrade to schedule auto-audits</p>
        <p class="text-xs text-canvas-muted">
          Paid plans let you pick a weekly, bi-weekly, or monthly cadence per business — and
          email you the moment your score moves.
        </p>
      </div>
      <a class="btn-primary w-full sm:w-auto" href="/billing">See paid plan</a>
    </div>
  {/if}

  {#if errorMessage}
    <div
      class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700"
      in:fade={{ duration: 220 }}
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
      in:fade={{ duration: 260 }}
    >
      <p class="text-2xl">👋</p>
      <h2 class="text-lg font-semibold text-canvas-ink">No businesses yet</h2>
      <p class="text-sm text-canvas-muted">
        Add your first business and we'll quietly start checking on it — Google Maps,
        your website, Instagram, and how your name and number look across the web.
      </p>
      <a class="btn-primary w-full sm:w-auto" href="/">Add a business</a>
    </div>
  {:else}
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
          in:fly={{ y: 12, delay: 60 * i, duration: 320, easing: quintOut }}
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
    <div class="flex flex-wrap items-center gap-3">
      {#if !atBusinessLimit}
        <a class="btn-ghost w-full sm:w-auto" href="/?add=1">+ Add another business</a>
      {:else if tier === 'free'}
        <div
          class="card flex w-full flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
        >
          <p class="text-sm text-canvas-ink">
            Paid keeps watching this business every week — auto-audits, competitor tracking, and a
            Monday digest the moment your score moves.
          </p>
          <a class="btn-primary w-full sm:w-auto" href="/billing">See paid plan</a>
        </div>
      {:else if overBusinessLimit}
        <p class="text-xs text-canvas-muted">
          You're tracking {businesses.length} businesses but your plan covers {businessLimit}.
          We'll keep everything visible — archive one to add a new business going forward.
        </p>
      {:else}
        <div
          class="card flex w-full flex-col gap-3 px-4 py-3 sm:flex-row sm:items-center sm:justify-between"
        >
          <p class="text-sm text-canvas-ink">
            Pro covers one business. Max tracks up to 10 — built for multi-location owners and agencies.
          </p>
          <a class="btn-primary w-full sm:w-auto" href="/billing">See Max</a>
        </div>
      {/if}
    </div>
  {/if}
</section>
