<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  import { fade, fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser, refreshCurrentUser } from '$lib/auth.svelte.js';
  import {
    getSubscriptionState,
    startSubscriptionCheckout,
    loadRazorpayCheckout
  } from '$lib/api.js';
  import { TIERS, TIER_ORDER } from '$lib/tiers.js';
  import { reduced } from '$lib/motion.js';
  import Skeleton from '$lib/components/Skeleton.svelte';

  /** @type {any} */
  let subscriptionData = $state(null);
  let loading = $state(true);
  let error = $state(/** @type {string | null} */ (null));
  let upgrading = $state(false);
  let upgradingTier = $state(/** @type {string | null} */ (null));
  let upgradeMessage = $state(/** @type {string | null} */ (null));

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user) {
      await goto('/login', { replaceState: true });
      return;
    }
    try {
      subscriptionData = await getSubscriptionState();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not load your subscription.';
    } finally {
      loading = false;
    }
  });

  const tier = $derived(subscriptionData?.tier ?? authState.user?.plan ?? 'free');
  // "Paying" = Pro ('paid') OR Max. Only Free is unsubscribed.
  const isPaid = $derived(tier !== 'free');
  const isMax = $derived(tier === 'max');
  const planLabel = $derived(tier === 'max' ? 'Max' : tier === 'paid' ? 'Pro' : 'Free');
  const limits = $derived(subscriptionData?.limits ?? { businesses: 1, audits_per_week: 1 });
  const businessCount = $derived(subscriptionData?.business_count ?? 0);
  const subscription = $derived(subscriptionData?.subscription ?? null);

  // --- Plan switcher (pill + swipe) ---
  const rank = { free: 0, paid: 1, max: 2 };
  // Default to the user's current paid tier, or Pro for free users (the
  // "most chosen" upsell). Set once, after state loads, so it doesn't fight
  // the user's own pill taps.
  let selected = $state(/** @type {'free' | 'paid' | 'max'} */ ('paid'));
  let selectedSet = false;
  $effect(() => {
    if (subscriptionData && !selectedSet) {
      selected = tier === 'free' ? 'paid' : tier;
      selectedSet = true;
    }
  });
  const selectedIndex = $derived(TIER_ORDER.indexOf(selected));
  const selectedMeta = $derived(TIERS[selected]);
  const selectedRank = $derived(rank[selected]);
  const currentRank = $derived(rank[/** @type {'free' | 'paid' | 'max'} */ (tier)] ?? 0);

  /** @param {number} i */
  function selectIndex(i) {
    selected = TIER_ORDER[Math.max(0, Math.min(TIER_ORDER.length - 1, i))];
  }

  // Swipe left/right to move between plans.
  let touchStartX = 0;
  /** @param {TouchEvent} e */
  function onTouchStart(e) {
    touchStartX = e.changedTouches[0].clientX;
  }
  /** @param {TouchEvent} e */
  function onTouchEnd(e) {
    const dx = e.changedTouches[0].clientX - touchStartX;
    if (Math.abs(dx) < 40) return; // ignore taps / tiny drags
    selectIndex(selectedIndex + (dx < 0 ? 1 : -1));
  }

  /** @param {'paid' | 'max'} planTier */
  async function handleUpgrade(planTier = 'paid') {
    if (upgrading) return;
    upgrading = true;
    upgradingTier = planTier;
    upgradeMessage = null;
    error = null;
    const planName = planTier === 'max' ? 'Max' : 'Pro';
    try {
      const checkout = await startSubscriptionCheckout(planTier);
      if (checkout.mock) {
        // Mock mode: backend already activated the subscription. Just refresh.
        upgradeMessage = `You're on the ${planName} plan. Welcome aboard.`;
        await Promise.all([refreshCurrentUser(), reloadState()]);
        return;
      }
      // Live Razorpay test-mode flow.
      await loadRazorpayCheckout();
      const RazorpayCtor = /** @type {any} */ (window).Razorpay;
      const rzp = new RazorpayCtor({
        key: checkout.razorpay_key_id,
        subscription_id: checkout.razorpay_subscription_id,
        name: 'Local SEO Health Monitor',
        description:
          planTier === 'max'
            ? 'Max plan — multi-location monitoring, up to 10 businesses'
            : 'Pro plan — weekly auto-audits, competitor tracking, Monday digest',
        handler: async () => {
          upgradeMessage = "Payment received. We're confirming with Razorpay…";
          // The actual state flip happens on the webhook; poll once after a
          // short delay so the UI catches up.
          setTimeout(async () => {
            await Promise.all([refreshCurrentUser(), reloadState()]);
          }, 1500);
        },
        modal: {
          ondismiss: () => {
            upgrading = false;
            upgradingTier = null;
          }
        },
        theme: { color: '#4f8c5b' }
      });
      rzp.open();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not start the upgrade.';
    } finally {
      // For mock mode we finish here; for live mode `ondismiss` clears it.
      if (subscriptionData?.tier !== 'free') {
        upgrading = false;
        upgradingTier = null;
      }
    }
  }

  async function reloadState() {
    try {
      subscriptionData = await getSubscriptionState();
    } catch {
      /* keep last good state */
    }
  }

  /** @param {string | null | undefined} value */
  function fmtDate(value) {
    if (!value) return null;
    try {
      return new Date(value).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      });
    } catch {
      return null;
    }
  }
</script>

<section class="space-y-8">
  <header>
    <p
      class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
    >
      <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
      Billing &amp; plan
    </p>
    <h1 class="mt-3 text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
      Your subscription
    </h1>
    <p class="mt-2 text-sm text-canvas-muted">
      Free shows you the score. Paid keeps watching — and tells you the moment it moves.
    </p>
  </header>

  {#if loading}
    <div class="space-y-4" aria-busy="true" aria-live="polite">
      <span class="sr-only">Loading your plan…</span>
      <Skeleton height="h-48" width="w-full" rounded="2xl" />
      <div class="grid gap-4 sm:grid-cols-2">
        <Skeleton height="h-44" width="w-full" rounded="2xl" />
        <Skeleton height="h-44" width="w-full" rounded="2xl" />
      </div>
    </div>
  {:else if error}
    <div
      class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700"
      in:fade={{ duration: 220 }}
    >
      <p class="text-2xl">🌧️</p>
      <p class="mt-2 font-medium">We couldn't load your subscription right now.</p>
      <p class="mt-1 text-action-700/80">{error}</p>
      <button
        type="button"
        class="btn-primary mt-3"
        onclick={() => location.reload()}
      >
        ↻ Try again
      </button>
    </div>
  {:else}
    <div class="card p-6 sm:p-8">
      <div class="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p class="text-xs uppercase tracking-wide text-canvas-muted">Current plan</p>
          <p class="mt-1 text-2xl font-semibold text-canvas-ink">
            {planLabel}
          </p>
          <p class="mt-1 text-sm text-canvas-muted">
            {limits.businesses} {limits.businesses === 1 ? 'business' : 'businesses'} ·
            up to {limits.audits_per_week} {limits.audits_per_week === 1 ? 'audit' : 'audits'}/week
          </p>
        </div>
        <span
          class={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium ${
            isPaid
              ? 'bg-healthy-50 text-healthy-700'
              : 'bg-canvas-soft text-canvas-muted'
          }`}
        >
          {#if isPaid}● Active{:else}Free tier{/if}
        </span>
      </div>

      <div class="mt-5 rounded-2xl bg-canvas-soft px-4 py-3 text-sm text-canvas-ink">
        You're using <strong>{businessCount}</strong> of {limits.businesses}
        {limits.businesses === 1 ? 'business' : 'business slots'} on this plan.
      </div>

      {#if subscription && isPaid}
        <dl class="mt-5 grid gap-3 text-sm text-canvas-ink sm:grid-cols-2">
          <div>
            <dt class="text-xs uppercase tracking-wide text-canvas-muted">Status</dt>
            <dd class="mt-0.5 capitalize">{subscription.status}</dd>
          </div>
          {#if subscription.next_billing_date}
            <div>
              <dt class="text-xs uppercase tracking-wide text-canvas-muted">Next billing</dt>
              <dd class="mt-0.5">{fmtDate(subscription.next_billing_date)}</dd>
            </div>
          {/if}
          {#if subscription.razorpay_subscription_id}
            <div class="sm:col-span-2">
              <dt class="text-xs uppercase tracking-wide text-canvas-muted">Razorpay reference</dt>
              <dd class="mt-0.5 break-all font-mono text-xs">
                {subscription.razorpay_subscription_id}
              </dd>
            </div>
          {/if}
        </dl>
      {/if}

      {#if upgradeMessage}
        <p
          class="mt-5 flex items-center gap-2 rounded-xl bg-healthy-50 px-3 py-2 text-sm text-healthy-700"
          in:fly={{ y: 4, duration: 240 }}
        >
          <span aria-hidden="true">✓</span>
          <span>{upgradeMessage}</span>
        </p>
      {/if}
    </div>

    <!-- Plan switcher: a pill toggles Free / Pro / Max, and the single card
         below swaps to the selected plan. Swipe left/right works too. -->
    <div class="space-y-4">
      <h2 class="text-sm font-semibold uppercase tracking-wide text-canvas-muted">
        Choose your plan
      </h2>

      <div
        class="relative flex rounded-2xl border border-canvas-soft bg-canvas-soft/40 p-1"
        role="tablist"
        aria-label="Plans"
      >
        <span
          class="pointer-events-none absolute bottom-1 left-1 top-1 rounded-xl bg-white shadow-soft transition-transform duration-200 ease-out motion-reduce:transition-none"
          style="width: calc((100% - 0.5rem) / 3); transform: translateX({selectedIndex * 100}%);"
          aria-hidden="true"
        ></span>
        {#each TIER_ORDER as key, i}
          <button
            type="button"
            role="tab"
            aria-selected={selected === key}
            onclick={() => selectIndex(i)}
            class={`relative z-10 flex-1 rounded-xl px-3 py-2 text-sm font-medium transition-colors duration-200 ${
              selected === key ? 'text-canvas-ink' : 'text-canvas-muted hover:text-canvas-ink'
            }`}
          >
            {TIERS[key].name}
            {#if tier === key}
              <span class="ml-1 text-[10px] font-normal text-canvas-muted">· current</span>
            {/if}
          </button>
        {/each}
      </div>

      <div
        role="group"
        aria-label="Selected plan details"
        ontouchstart={onTouchStart}
        ontouchend={onTouchEnd}
      >
        {#key selected}
          <div
            class={`card p-6 sm:p-8 ${
              selected === 'paid'
                ? 'border-healthy-100 bg-healthy-50/30'
                : selected === 'max'
                  ? 'border-attention-100 bg-attention-50/30'
                  : ''
            }`}
            in:fly={reduced({ y: 8, duration: 200, easing: quintOut })}
          >
            {#if selected === 'paid'}
              <span
                class="inline-flex items-center gap-1.5 rounded-full bg-healthy-100 px-3 py-1 text-xs font-medium text-healthy-700"
              >
                ★ Most chosen
              </span>
            {:else if selected === 'max'}
              <span
                class="inline-flex items-center gap-1.5 rounded-full bg-attention-100 px-3 py-1 text-xs font-medium text-attention-700"
              >
                Twice-weekly updates
              </span>
            {/if}

            <h3 class="mt-3 text-2xl font-semibold tracking-tight text-canvas-ink">
              AuditHealth
              <span class={selected === 'max' ? 'text-attention-700' : 'text-healthy-700'}>
                {selectedMeta.name}
              </span>
            </h3>
            <p class="mt-1 text-sm text-canvas-muted">{selectedMeta.tagline}</p>

            <p class="mt-5 flex items-baseline gap-1">
              <span class="text-4xl font-semibold tracking-tight text-canvas-ink">
                {selectedMeta.amount}
              </span>
              <span class="text-sm text-canvas-muted">{selectedMeta.cadence}</span>
            </p>

            <ul class="mt-5 space-y-3">
              {#each selectedMeta.features as feat}
                <li class="flex items-center gap-3 text-sm text-canvas-ink">
                  <span
                    class="grid h-5 w-5 shrink-0 place-items-center rounded-full bg-healthy-50 text-healthy-600"
                    aria-hidden="true"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="2.5"
                      stroke-linecap="round"
                      stroke-linejoin="round"
                      class="h-3 w-3"
                    >
                      <path d="M20 6 9 17l-5-5" />
                    </svg>
                  </span>
                  {feat}
                </li>
              {/each}
            </ul>

            <div class="mt-6">
              {#if selected === tier}
                <p
                  class="rounded-xl bg-canvas-soft px-4 py-3 text-center text-sm font-medium text-canvas-ink"
                >
                  Your current plan
                </p>
              {:else if selectedRank > currentRank}
                <button
                  type="button"
                  class="btn-primary w-full"
                  onclick={() => handleUpgrade(/** @type {'paid' | 'max'} */ (selected))}
                  disabled={upgrading}
                >
                  {upgrading && upgradingTier === selected
                    ? 'Starting checkout…'
                    : `Upgrade to ${selectedMeta.name}`}
                </button>
                <p class="mt-3 text-center text-xs text-canvas-muted">
                  Razorpay Test Mode — no real card will be charged.
                </p>
              {:else}
                <a href="/account" class="btn-ghost w-full">Manage in Account</a>
                <p class="mt-3 text-center text-xs text-canvas-muted">
                  Downgrades &amp; cancellation live on your account page.
                </p>
              {/if}
            </div>
          </div>
        {/key}
      </div>

      <p class="text-center text-xs text-canvas-muted">Swipe or tap a plan to compare.</p>
    </div>
  {/if}
</section>
