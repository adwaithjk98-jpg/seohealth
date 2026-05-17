<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';

  import { fade, fly } from 'svelte/transition';

  import { authState, loadCurrentUser, refreshCurrentUser } from '$lib/auth.svelte.js';
  import {
    getSubscriptionState,
    startSubscriptionCheckout,
    loadRazorpayCheckout
  } from '$lib/api.js';
  import Skeleton from '$lib/components/Skeleton.svelte';

  /** @type {any} */
  let subscriptionData = $state(null);
  let loading = $state(true);
  let error = $state(/** @type {string | null} */ (null));
  let upgrading = $state(false);
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
  const isPaid = $derived(tier === 'paid');
  const limits = $derived(subscriptionData?.limits ?? { businesses: 1, audits_per_week: 1 });
  const businessCount = $derived(subscriptionData?.business_count ?? 0);
  const subscription = $derived(subscriptionData?.subscription ?? null);

  async function handleUpgrade() {
    if (upgrading) return;
    upgrading = true;
    upgradeMessage = null;
    error = null;
    try {
      const checkout = await startSubscriptionCheckout('paid');
      if (checkout.mock) {
        // Mock mode: backend already activated the subscription. Just refresh.
        upgradeMessage = "You're on the paid plan. Welcome aboard.";
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
        description: 'Paid plan — 3 businesses, weekly health checks',
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
          }
        },
        theme: { color: '#4f8c5b' }
      });
      rzp.open();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not start the upgrade.';
    } finally {
      // For mock mode we finish here; for live mode `ondismiss` clears it.
      if (subscriptionData?.tier === 'paid') upgrading = false;
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
      Pick the plan that matches how many businesses you want to keep healthy.
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
            {isPaid ? 'Paid' : 'Free'}
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

    <div class="grid gap-4 sm:grid-cols-2">
      <div class="card p-5">
        <p class="text-xs uppercase tracking-wide text-canvas-muted">Free</p>
        <p class="mt-1 text-xl font-semibold text-canvas-ink">₹0 / month</p>
        <ul class="mt-3 space-y-1.5 text-sm text-canvas-ink">
          <li>1 business</li>
          <li>Monthly auto-audit</li>
          <li>Plain-English recommendations</li>
        </ul>
        <p class="mt-4 text-xs text-canvas-muted">
          {isPaid ? 'Switch from paid in support.' : "You're on this plan."}
        </p>
      </div>
      <div class="card border border-healthy-100 bg-healthy-50/40 p-5">
        <p class="text-xs uppercase tracking-wide text-healthy-700">Paid</p>
        <p class="mt-1 text-xl font-semibold text-canvas-ink">₹399 / month</p>
        <ul class="mt-3 space-y-1.5 text-sm text-canvas-ink">
          <li>Up to 3 businesses</li>
          <li>Weekly auto-audits</li>
          <li>Step-by-step guided fixes</li>
        </ul>
        {#if !isPaid}
          <button
            type="button"
            class="btn-primary mt-4 w-full"
            onclick={handleUpgrade}
            disabled={upgrading}
          >
            {upgrading ? 'Starting checkout…' : 'Upgrade to paid'}
          </button>
          <p class="mt-3 text-center text-xs text-canvas-muted">
            Razorpay Test Mode — no real card will be charged.
          </p>
        {:else}
          <p class="mt-4 text-center text-xs text-healthy-700 font-medium">
            You're on the paid plan.
          </p>
        {/if}
      </div>
    </div>
  {/if}
</section>
