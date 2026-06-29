<script>
  import { onMount } from 'svelte';
  import { goto, invalidateAll } from '$app/navigation';
  import { fly, fade } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import {
    getAuditQuota,
    getInstagramEligibility,
    setBusinessSchedule,
    startAudit
  } from '$lib/api.js';
  import { formatRelativeTime } from '$lib/dashboard.js';
  import { PRO, MAX } from '$lib/tiers.js';

  /** @type {{ data: { businesses: any[] | null, error: string | null } }} */
  let { data } = $props();

  // Local copy of the businesses list so cadence edits update in place
  // without a full page reload. We re-seed from `data.businesses`
  // whenever the loader hands us a fresh array.
  let businesses = $state(/** @type {any[]} */ (data?.businesses ?? []));
  $effect(() => {
    businesses = /** @type {any[]} */ (data?.businesses ?? []);
  });

  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );

  const subState = $derived(authState.user?.subscription_state ?? null);
  const tier = $derived(subState?.tier ?? authState.user?.plan ?? 'free');
  const isPaid = $derived(tier !== 'free');

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

  /** Same format helper but day-precision — used for the schedule rows
   * where the time of day adds noise. */
  function formatScheduleDate(/** @type {string | null} */ value) {
    if (!value) return null;
    const iso = /Z|[+-]\d{2}:?\d{2}$/.test(value) ? value : `${value}Z`;
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return null;
    return date.toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric'
    });
  }

  // --- Inline schedule editing ---
  // The Audit tab is now the single source of truth for cadence — the
  // per-business detail page only shows a read-only line linking back
  // here. Each row tracks its own saving state so concurrent edits on
  // different businesses don't block each other.
  /** @type {Record<number, string | null>} */
  let scheduleSaving = $state({});
  /** @type {Record<number, string>} */
  let scheduleError = $state({});

  // Twice-weekly is a Max-only cadence (the backend rejects it for other tiers),
  // so only offer it when the user is on Max.
  const cadenceOptions = $derived([
    { value: null, label: 'Off' },
    ...(tier === 'max' ? [{ value: 'twice-weekly', label: 'Twice a week' }] : []),
    { value: 'weekly', label: 'Weekly' },
    { value: 'biweekly', label: 'Bi-weekly' },
    { value: 'monthly', label: 'Monthly' }
  ]);

  /** @param {any} biz @param {'twice-weekly' | 'weekly' | 'biweekly' | 'monthly' | null} next */
  async function handleSetCadence(biz, next) {
    if (!isPaid || scheduleSaving[biz.id]) return;
    if (biz.audit_schedule_cadence === next) return;
    scheduleSaving = { ...scheduleSaving, [biz.id]: next ?? 'off' };
    scheduleError = { ...scheduleError, [biz.id]: '' };
    try {
      const updated = await setBusinessSchedule(biz.id, next);
      businesses = businesses.map((b) => (b.id === biz.id ? { ...b, ...updated } : b));
    } catch (err) {
      scheduleError = {
        ...scheduleError,
        [biz.id]: err instanceof Error ? err.message : 'Could not save your schedule.'
      };
    } finally {
      scheduleSaving = { ...scheduleSaving, [biz.id]: null };
    }
  }

  // --- Manual audits ---
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
      await goto(`/audits/${result.audit_id}`);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not start audit.';
      runError = { ...runError, [biz.id]: message };
      runState = { ...runState, [biz.id]: 'idle' };
      await loadQuota();
    }
  }

  // --- Pre-audit Instagram eligibility ---
  // Probe (cheap — Graph-cached, no audit-quota cost) so we can warn a user
  // their IG won't be tracked BEFORE they spend a weekly audit credit on it.
  /** @type {Record<number, { eligible: boolean | null, note: string | null }>} */
  let igElig = $state({});

  async function loadIgEligibility() {
    for (const biz of businesses) {
      if (!biz.ig_handle || biz.id in igElig) continue;
      try {
        const res = await getInstagramEligibility(biz.id);
        igElig = { ...igElig, [biz.id]: { eligible: res.eligible, note: res.note } };
      } catch {
        // Unknown — stay silent rather than guess.
        igElig = { ...igElig, [biz.id]: { eligible: null, note: null } };
      }
    }
  }

  $effect(() => {
    if (authState.loaded && authState.user) {
      loadQuota();
    }
  });

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user || data?.error === 'unauthenticated') {
      await goto('/login', { replaceState: true });
      return;
    }
    loadIgEligibility();
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
      Set a cadence and we'll keep an eye on things. Run a manual audit anytime you want a
      fresh look.
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
    <!-- ===== HERO: Schedule auto-audits ===== -->
    {#if isPaid}
      <section
        class="card border-healthy-100 bg-gradient-to-br from-healthy-50/70 via-attention-50/30 to-white p-5 sm:p-7"
        in:fade={{ duration: 220 }}
      >
        <div class="flex items-start gap-4">
          <span
            class="relative grid h-12 w-12 shrink-0 place-items-center"
            aria-hidden="true"
          >
            <span class="absolute inset-0 animate-pulse rounded-full bg-healthy-200/40"></span>
            <span
              class="relative grid h-10 w-10 place-items-center rounded-full bg-white text-healthy-700 shadow-sm"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
                class="h-5 w-5"
              >
                <circle cx="12" cy="12" r="9" />
                <path d="M12 7v5l3 2" />
              </svg>
            </span>
          </span>
          <div class="min-w-0 flex-1">
            <p
              class="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-healthy-700"
            >
              <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
              Auto-audit schedule
            </p>
            <p class="mt-1 text-base font-semibold tracking-tight text-canvas-ink sm:text-lg">
              Set it once. We'll do the watching.
            </p>
            <p class="mt-1 text-xs text-canvas-muted">
              Pick a cadence per business — we re-check on that rhythm and email you only when
              scores move.
            </p>
          </div>
        </div>

        <ul class="mt-5 space-y-3">
          {#each businesses as biz, i (biz.id)}
            {@const cadence = biz.audit_schedule_cadence ?? null}
            {@const next = biz.next_auto_audit_at}
            {@const saving = scheduleSaving[biz.id] ?? null}
            <li
              class="rounded-2xl border border-canvas-soft bg-white p-4 shadow-sm"
              in:fly={{ y: 6, delay: 30 * i, duration: 220, easing: quintOut }}
            >
              <div class="flex flex-wrap items-start justify-between gap-2">
                <div class="min-w-0">
                  <p class="truncate text-sm font-semibold text-canvas-ink">{biz.name}</p>
                  <p class="text-xs text-canvas-muted">
                    {biz.city}{biz.country ? ` · ${biz.country}` : ''}
                  </p>
                </div>
                {#if cadence && next}
                  <span
                    class="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-healthy-50 px-2.5 py-0.5 text-xs font-medium text-healthy-700"
                  >
                    <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
                    Next {formatScheduleDate(next)}
                  </span>
                {:else if cadence}
                  <span
                    class="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-healthy-50 px-2.5 py-0.5 text-xs font-medium text-healthy-700"
                  >
                    <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
                    On · {cadence}
                  </span>
                {/if}
              </div>

              <div
                role="radiogroup"
                aria-label={`Cadence for ${biz.name}`}
                class="mt-3 grid grid-cols-4 gap-1.5"
              >
                {#each cadenceOptions as opt}
                  {@const selected = cadence === opt.value}
                  {@const isSaving = saving === (opt.value ?? 'off')}
                  <button
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    disabled={saving !== null}
                    onclick={() =>
                      handleSetCadence(
                        biz,
                        /** @type {'twice-weekly' | 'weekly' | 'biweekly' | 'monthly' | null} */ (
                          opt.value
                        )
                      )}
                    class={`min-h-[36px] rounded-xl border px-2 py-1.5 text-xs font-medium transition ${
                      selected
                        ? 'border-healthy-300 bg-healthy-50 text-healthy-700'
                        : 'border-canvas-soft bg-white text-canvas-ink hover:border-canvas-muted/40'
                    } disabled:cursor-wait disabled:opacity-70`}
                  >
                    {isSaving ? '…' : opt.label}
                  </button>
                {/each}
              </div>

              {#if scheduleError[biz.id]}
                <p
                  class="mt-2 rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700"
                  role="alert"
                  in:fade={{ duration: 160 }}
                >
                  {scheduleError[biz.id]}
                </p>
              {/if}
            </li>
          {/each}
        </ul>
      </section>
    {:else}
      <!-- Free-tier upsell — still leads, framed as the calmer default. -->
      <section
        class="card relative overflow-hidden border-healthy-100 bg-gradient-to-br from-healthy-50/70 via-attention-50/30 to-white p-6 sm:p-7"
        in:fade={{ duration: 220 }}
      >
        <div class="flex items-start gap-4">
          <div
            class="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-white text-2xl shadow-sm"
            aria-hidden="true"
          >
            🔒
          </div>
          <div class="min-w-0 flex-1">
            <p
              class="inline-flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-healthy-700"
            >
              <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
              Auto-audit schedule
            </p>
            <p class="mt-1 text-base font-semibold tracking-tight text-canvas-ink sm:text-lg">
              Let us watch for you.
            </p>
            <p class="mt-1 max-w-md text-xs text-canvas-muted">
              Pro re-checks each business on a cadence — weekly, bi-weekly or monthly — and
              emails you only when your score moves.
            </p>
            <a class="btn-primary mt-3 inline-flex" href="/billing">Upgrade to Pro</a>
          </div>
        </div>
      </section>
    {/if}

    <!-- ===== Manual audits ===== -->
    <section class="space-y-3">
      <div class="flex flex-wrap items-end justify-between gap-2">
        <h2 class="text-sm font-semibold uppercase tracking-wide text-canvas-muted">
          Or run an audit now
        </h2>
        {#if quota}
          <p class="text-xs text-canvas-muted">
            <span class="font-medium text-canvas-ink">{quota.remaining}</span>
            of {quota.limit} left this week · resets {formatReset(quota.period_end)}
          </p>
        {:else if quotaLoading}
          <p class="text-xs text-canvas-muted">Loading quota…</p>
        {:else if quotaError}
          <p class="text-xs text-action-700">{quotaError}</p>
        {/if}
      </div>

      {#if atCap}
        <p
          class="rounded-xl bg-attention-50 px-3 py-2 text-xs text-attention-700"
          transition:fade={{ duration: 180 }}
        >
          You've used every audit in your weekly allowance. A slot reopens
          {formatReset(quota?.period_end ?? null)}.
          {#if !isPaid}
            <a class="ml-1 font-medium text-attention-700 underline" href="/billing">
              Upgrade to Pro
            </a>
            for {PRO.auditsPerWeek} checks a week.
          {:else if tier === 'paid'}
            <!-- Only sanctioned Pro -> Max nudge: factual, shown once at the
                 cap, never repeated, never a banner. -->
            <a class="ml-1 font-medium text-attention-700 underline" href="/billing">
              Max
            </a>
            runs {MAX.auditsPerWeek} a week, if you ever need them.
          {/if}
        </p>
      {/if}

      <ul class="space-y-3">
        {#each businesses as biz, i (biz.id)}
          {@const running = !!biz.running_audit_id}
          {@const starting = runState[biz.id] === 'starting'}
          {@const disabled = atCap || running || starting}
          <li in:fly={{ y: 6, delay: 30 * i, duration: 220, easing: quintOut }}>
            <div
              class="card flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5"
            >
              <div class="min-w-0 flex-1">
                <p class="truncate text-base font-semibold tracking-tight text-canvas-ink">
                  {biz.name}
                </p>
                <div class="mt-1 flex flex-wrap items-center gap-2 text-xs text-canvas-muted">
                  <span>{biz.city}{biz.country ? ` · ${biz.country}` : ''}</span>
                  {#if biz.latest_audit_finished_at}
                    <span>· Last audit {formatRelativeTime(biz.latest_audit_finished_at)}</span>
                  {/if}
                </div>
                {#if igElig[biz.id]?.eligible === false}
                  <p
                    class="mt-2 rounded-xl bg-attention-50 px-3 py-2 text-xs leading-relaxed text-attention-700"
                    in:fade={{ duration: 160 }}
                  >
                    {igElig[biz.id].note} Switch it to a Business or Creator account to
                    track Instagram — running an audit now won't include it and still
                    uses a credit.
                  </p>
                {/if}
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
                    In progress · watch
                  </a>
                {:else}
                  <button
                    type="button"
                    class="btn-ghost w-full sm:w-auto"
                    onclick={() => handleRun(biz)}
                    disabled={disabled}
                    title={atCap ? 'You are at your weekly audit limit' : ''}
                  >
                    {starting ? 'Starting…' : 'Run audit'}
                  </button>
                {/if}
              </div>
            </div>
          </li>
        {/each}
      </ul>
    </section>
  {/if}
</section>
