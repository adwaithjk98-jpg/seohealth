<script>
  import { onMount } from 'svelte';
  import { goto, invalidateAll } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import { getAuditQuota, startAudit } from '$lib/api.js';
  import { formatRelativeTime } from '$lib/dashboard.js';

  /** @type {{ data: { businesses: any[] | null, error: string | null } }} */
  let { data } = $props();

  const businesses = $derived(data?.businesses ?? []);
  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );

  const subState = $derived(authState.user?.subscription_state ?? null);
  const tier = $derived(subState?.tier ?? authState.user?.plan ?? 'free');
  const isPaid = $derived(tier === 'paid');

  // --- Quota ---
  let quota = $state(
    /** @type {{ used: number, limit: number, remaining: number, period_end: string, tier: string } | null} */ (
      null
    )
  );
  let quotaLoading = $state(false);
  let quotaError = $state(/** @type {string | null} */ (null));

  async function loadQuota() {
    quotaLoading = true;
    quotaError = null;
    try {
      quota = await getAuditQuota();
    } catch (err) {
      quotaError = err instanceof Error ? err.message : 'Could not load your audit quota.';
    } finally {
      quotaLoading = false;
    }
  }

  const atCap = $derived(quota != null && quota.remaining <= 0);

  /** @param {string | null} value */
  function formatReset(value) {
    if (!value) return null;
    const iso = /Z|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit'
    });
  }

  // --- Run audit ---
  /** @type {Record<number, 'idle' | 'starting'>} */
  let runState = $state({});
  /** @type {Record<number, string>} */
  let runError = $state({});

  /** @param {any} biz */
  async function handleRun(biz) {
    if (atCap || biz.running_audit_id) return;
    runState = { ...runState, [biz.id]: 'starting' };
    runError = { ...runError, [biz.id]: '' };
    try {
      const result = await startAudit(biz.id);
      // Jump straight to the audit detail so the user sees progress
      // streaming live — same handoff the dashboard tile uses.
      await goto(`/audits/${result.audit_id}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not start audit.';
      runError = { ...runError, [biz.id]: message };
      runState = { ...runState, [biz.id]: 'idle' };
      // Refresh quota in case the failure was a 429 — the counter on
      // screen should match server state.
      await loadQuota();
    }
  }

  // --- Scheduled panel data ---
  // Auto-audits are paid-only (see services/auto_audit.py). Each
  // business has `next_auto_audit_at` set by the scheduler when active.
  const scheduledBusinesses = $derived(
    businesses.filter((/** @type {any} */ b) => b.next_auto_audit_at != null)
  );

  $effect(() => {
    if (authState.loaded && authState.user) {
      loadQuota();
    }
  });

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user || data?.error === 'unauthenticated') {
      await goto('/login', { replaceState: true });
    }
  });
</script>

<section class="space-y-8">
  <header>
    <span
      class="inline-flex items-center gap-2 rounded-full border border-healthy-200 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
    >
      <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
      Audit Workspace
    </span>
    <h1 class="mt-4 text-2xl font-semibold tracking-tight text-canvas-ink sm:text-3xl">
      Audits
    </h1>
    <p class="mt-2 max-w-2xl text-sm leading-relaxed text-canvas-muted">
      Run a fresh health check on any of your businesses, or let us auto-audit weekly so you
      never miss a slip.
    </p>
  </header>

  {#if errorMessage}
    <div
      class="rounded-2xl border border-action-100 bg-action-50 p-6 text-sm text-action-700 shadow-soft"
    >
      <p class="font-semibold">We couldn't load your businesses.</p>
      <p class="mt-1 text-action-700/80">{errorMessage}</p>
    </div>
  {:else if businesses.length === 0}
    <div
      class="card mx-auto flex max-w-md flex-col items-center gap-4 px-6 py-12 text-center sm:px-10"
    >
      <div
        class="grid h-16 w-16 place-items-center rounded-2xl bg-healthy-50 text-3xl"
        aria-hidden="true"
      >
        🩺
      </div>
      <h2 class="text-lg font-semibold tracking-tight text-canvas-ink">
        Add a business first
      </h2>
      <p class="text-sm leading-relaxed text-canvas-muted">
        Audits run against a business you own. Add one and we'll do the rest.
      </p>
      <a class="btn-primary w-full sm:w-auto" href="/">Add a business</a>
    </div>
  {:else}
    <!-- ===== Quota card ===== -->
    <section
      class="card border-healthy-100 bg-gradient-to-br from-healthy-50/60 to-white p-6 sm:p-7"
      in:fade={{ duration: 220 }}
    >
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
            Manual audits this week
          </p>
          {#if quota}
            <p class="mt-2 flex items-baseline gap-1.5 text-canvas-ink">
              <span class="text-4xl font-semibold tracking-tight">{quota.remaining}</span>
              <span class="text-sm text-canvas-muted">
                of {quota.limit} remaining
              </span>
            </p>
            <p class="mt-1 text-xs text-canvas-muted">
              {quota.used} used · resets {formatReset(quota.period_end)}
            </p>
          {:else if quotaLoading}
            <p class="mt-2 text-sm text-canvas-muted">Loading quota…</p>
          {:else if quotaError}
            <p class="mt-2 text-sm text-action-700">{quotaError}</p>
          {/if}
        </div>
        <span
          class={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            atCap
              ? 'bg-attention-100 text-attention-700'
              : 'bg-healthy-100 text-healthy-700'
          }`}
        >
          <span
            class={`h-1.5 w-1.5 rounded-full ${
              atCap ? 'bg-attention-500' : 'bg-healthy-500'
            }`}
          ></span>
          {atCap ? 'At plan limit' : 'Ready to run'}
        </span>
      </div>

      {#if quota}
        <div
          class="mt-5 h-2 w-full overflow-hidden rounded-full bg-canvas-soft"
          role="progressbar"
          aria-valuemin="0"
          aria-valuemax={quota.limit}
          aria-valuenow={quota.used}
        >
          <div
            class={`h-full rounded-full transition-[width] duration-300 ease-out ${
              atCap ? 'bg-attention-500' : 'bg-healthy-500'
            }`}
            style={`width: ${Math.min(100, (quota.used / Math.max(1, quota.limit)) * 100)}%`}
          ></div>
        </div>
      {/if}

      {#if atCap}
        <p
          class="mt-4 rounded-xl bg-attention-50 px-3 py-2 text-xs text-attention-700"
          transition:fade={{ duration: 180 }}
        >
          You've used every audit in your weekly allowance. A slot reopens
          {formatReset(quota?.period_end ?? null)}.
          {#if !isPaid}
            <a class="ml-1 font-medium text-attention-700 underline" href="/billing">
              Upgrade to paid
            </a>
            for 7 per week.
          {/if}
        </p>
      {/if}
    </section>

    <!-- ===== Run a manual audit ===== -->
    <section class="space-y-3">
      <div class="flex items-end justify-between">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-canvas-muted">
          Run a manual audit
        </h2>
        <span class="text-xs text-canvas-muted">
          {businesses.length}
          {businesses.length === 1 ? 'business' : 'businesses'}
        </span>
      </div>

      <ul class="space-y-3">
        {#each businesses as biz, i (biz.id)}
          {@const running = !!biz.running_audit_id}
          {@const starting = runState[biz.id] === 'starting'}
          {@const disabled = atCap || running || starting}
          <li in:fly={{ y: 6, delay: 30 * i, duration: 240, easing: quintOut }}>
            <div
              class="card flex flex-col gap-3 p-5 sm:flex-row sm:items-center sm:justify-between"
            >
              <div class="min-w-0 flex-1">
                <p class="truncate text-base font-semibold tracking-tight text-canvas-ink">
                  {biz.name}
                </p>
                <p class="mt-0.5 text-xs text-canvas-muted">
                  {biz.city}{biz.country ? ` · ${biz.country}` : ''}
                </p>
                <div class="mt-2 flex flex-wrap items-center gap-2 text-xs">
                  {#if biz.latest_grade}
                    <span
                      class="inline-flex items-center rounded-full bg-healthy-50 px-2 py-0.5 font-medium text-healthy-700"
                    >
                      {biz.latest_grade}
                      {#if biz.latest_score != null}
                        · {biz.latest_score}/100
                      {/if}
                    </span>
                  {/if}
                  {#if biz.latest_audit_finished_at}
                    <span class="text-canvas-muted">
                      Last audit {formatRelativeTime(biz.latest_audit_finished_at)}
                    </span>
                  {:else}
                    <span class="text-canvas-muted">No audits yet</span>
                  {/if}
                </div>
                {#if runError[biz.id]}
                  <p class="mt-2 text-xs text-action-700">{runError[biz.id]}</p>
                {/if}
              </div>

              <div class="flex shrink-0 gap-2">
                {#if running}
                  <a
                    class="btn-ghost inline-flex w-full items-center gap-2 sm:w-auto"
                    href={`/audits/${biz.running_audit_id}`}
                  >
                    <span
                      class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-healthy-500"
                    ></span>
                    Audit in progress · watch
                  </a>
                {:else}
                  <button
                    type="button"
                    class="btn-primary w-full sm:w-auto"
                    onclick={() => handleRun(biz)}
                    disabled={disabled}
                    title={atCap ? 'You are at your weekly audit limit' : ''}
                  >
                    {starting ? 'Starting…' : 'Run manual audit'}
                  </button>
                {/if}
              </div>
            </div>
          </li>
        {/each}
      </ul>
    </section>

    <!-- ===== Scheduled audits ===== -->
    <section class="space-y-3">
      <div class="flex items-end justify-between">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-canvas-muted">
          Scheduled audits
        </h2>
        {#if isPaid}
          <span
            class="inline-flex items-center gap-1.5 rounded-full bg-healthy-100 px-2 py-0.5 text-xs font-medium text-healthy-700"
          >
            <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
            Paid plan
          </span>
        {/if}
      </div>

      {#if isPaid}
        <div class="card p-6">
          <div class="flex items-start gap-3">
            <div
              class="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-healthy-50 text-2xl"
              aria-hidden="true"
            >
              ⏰
            </div>
            <div class="min-w-0">
              <p class="text-sm font-semibold tracking-tight text-canvas-ink">
                Auto-audits run weekly
              </p>
              <p class="mt-1 text-xs leading-relaxed text-canvas-muted">
                We quietly re-check each of your businesses every 7 days and email you only
                when the score moves meaningfully. Nothing to configure — it's already on.
              </p>
            </div>
          </div>

          {#if scheduledBusinesses.length > 0}
            <ul class="mt-5 space-y-2">
              {#each scheduledBusinesses as biz (biz.id)}
                <li
                  class="flex items-center justify-between gap-3 rounded-xl border border-canvas-soft bg-white px-4 py-3 text-sm"
                >
                  <div class="min-w-0">
                    <p class="truncate font-medium text-canvas-ink">{biz.name}</p>
                    <p class="text-xs text-canvas-muted">{biz.city}</p>
                  </div>
                  <p class="shrink-0 text-xs text-canvas-muted">
                    Next: {formatReset(biz.next_auto_audit_at)}
                  </p>
                </li>
              {/each}
            </ul>
          {/if}
        </div>
      {:else}
        <!-- Free-tier pitch: identical layout, locked overlay. -->
        <div
          class="card relative overflow-hidden border-healthy-200 bg-gradient-to-br from-healthy-50/40 to-white p-6"
        >
          <div class="pointer-events-none opacity-50">
            <div class="flex items-start gap-3">
              <div
                class="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-healthy-50 text-2xl"
                aria-hidden="true"
              >
                ⏰
              </div>
              <div class="min-w-0">
                <p class="text-sm font-semibold tracking-tight text-canvas-ink">
                  Auto-audits run weekly
                </p>
                <p class="mt-1 text-xs leading-relaxed text-canvas-muted">
                  We quietly re-check each of your businesses every 7 days and email you only
                  when the score moves meaningfully.
                </p>
              </div>
            </div>
            <ul class="mt-5 space-y-2">
              <li
                class="flex items-center justify-between gap-3 rounded-xl border border-canvas-soft bg-white px-4 py-3 text-sm"
              >
                <div>
                  <p class="font-medium text-canvas-ink">Your business · Calicut</p>
                  <p class="text-xs text-canvas-muted">Sample preview</p>
                </div>
                <p class="text-xs text-canvas-muted">Next: every 7 days</p>
              </li>
            </ul>
          </div>

          <!-- Lock overlay -->
          <div
            class="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-white/40 px-6 text-center backdrop-blur-[2px]"
          >
            <div
              class="grid h-12 w-12 place-items-center rounded-2xl bg-healthy-500 text-white shadow-soft"
              aria-hidden="true"
            >
              🔒
            </div>
            <p class="text-sm font-semibold tracking-tight text-canvas-ink">
              Auto-audits are a paid feature
            </p>
            <p class="max-w-sm text-xs text-canvas-muted">
              Upgrade and we'll watch each business automatically — you only hear from us
              when your score moves.
            </p>
            <a class="btn-primary mt-1" href="/billing">Upgrade to unlock</a>
          </div>
        </div>
      {/if}
    </section>
  {/if}
</section>
