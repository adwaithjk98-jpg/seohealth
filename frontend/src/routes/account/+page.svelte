<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fade, fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import {
    authState,
    loadCurrentUser,
    refreshCurrentUser,
    updateCurrentUser,
    greetingName,
    logout
  } from '$lib/auth.svelte.js';
  import {
    cancelSubscription,
    startSubscriptionCheckout,
    exportMyData,
    deleteMyAccount
  } from '$lib/api.js';
  import { reduced } from '$lib/motion.js';
  import { getPushState, enablePush, disablePush, isPushSupported } from '$lib/push.js';

  let ready = $state(false);

  // TODO(launch): swap to a real domain support address (e.g. hello@yourdomain.in).
  const supportEmail = 'hello@yourdomain.in';
  const appVersion = '0.1.0';

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user) {
      await goto('/login', { replaceState: true });
      return;
    }
    ready = true;

    // Push state is device-local — reflect this browser's subscription. Hidden
    // until the backend has a VAPID key (st.available), so no broken toggle.
    if (isPushSupported()) {
      const st = await getPushState();
      pushSupported = st.supported;
      pushAvailable = st.available;
      pushSubscribed = st.subscribed;
    }
  });

  const user = $derived(authState.user);
  const tier = $derived(user?.subscription_state?.tier ?? user?.plan ?? 'free');
  const isFree = $derived(tier === 'free');
  const isMax = $derived(tier === 'max');
  const planLabel = $derived(tier === 'max' ? 'Max' : tier === 'paid' ? 'Pro' : 'Free');

  // --- Display name ---
  let nameDraft = $state('');
  let nameSaving = $state(false);
  $effect(() => {
    if (ready) nameDraft = user?.display_name ?? '';
  });
  async function saveName() {
    if (nameSaving) return;
    nameSaving = true;
    try {
      await updateCurrentUser({ display_name: nameDraft.trim() });
    } finally {
      nameSaving = false;
    }
  }

  // --- Weekly digest toggle ---
  let digestSaving = $state(false);
  async function toggleDigest() {
    if (digestSaving) return;
    digestSaving = true;
    try {
      await updateCurrentUser({ weekly_digest_enabled: !user?.weekly_digest_enabled });
    } finally {
      digestSaving = false;
    }
  }

  // --- Push notifications (this device) ---
  let pushSupported = $state(false);
  let pushAvailable = $state(false);
  let pushSubscribed = $state(false);
  let pushBusy = $state(false);
  let pushError = $state(/** @type {string | null} */ (null));

  async function togglePush() {
    if (pushBusy) return;
    pushBusy = true;
    pushError = null;
    try {
      if (pushSubscribed) {
        await disablePush();
        pushSubscribed = false;
      } else {
        pushSubscribed = await enablePush();
        if (!pushSubscribed) pushError = 'Push isn’t available right now.';
      }
    } catch (err) {
      pushError =
        err && /** @type {any} */ (err).code === 'denied'
          ? 'Notifications are blocked. Enable them in your browser settings, then try again.'
          : err instanceof Error
            ? err.message
            : 'Could not update notifications.';
    } finally {
      pushBusy = false;
    }
  }

  // --- Plan management ---
  let planBusy = $state(false);
  let planMessage = $state(/** @type {string | null} */ (null));
  let planError = $state(/** @type {string | null} */ (null));

  let confirmingCancel = $state(false);
  async function doCancel() {
    if (planBusy) return;
    planBusy = true;
    planError = null;
    try {
      await cancelSubscription();
      await refreshCurrentUser();
      confirmingCancel = false;
      planMessage = "Your subscription is cancelled — you're back on Free.";
    } catch (err) {
      planError = err instanceof Error ? err.message : 'Could not cancel right now.';
    } finally {
      planBusy = false;
    }
  }

  // Max → Pro. In mock mode the checkout flips the tier immediately; with live
  // Razorpay this is the tier-change flow.
  async function downgradeToPro() {
    if (planBusy) return;
    planBusy = true;
    planError = null;
    try {
      const checkout = await startSubscriptionCheckout('paid');
      if (checkout.mock) {
        await refreshCurrentUser();
        planMessage = "You're on the Pro plan now.";
      } else {
        planError = 'Tier changes need the live billing flow (coming soon).';
      }
    } catch (err) {
      planError = err instanceof Error ? err.message : 'Could not change your plan right now.';
    } finally {
      planBusy = false;
    }
  }

  // --- Data export ---
  let exporting = $state(false);
  async function downloadData() {
    if (exporting) return;
    exporting = true;
    try {
      const data = await exportMyData();
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `audithealth-export-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      /* surfaced rarely; keep it quiet */
    } finally {
      exporting = false;
    }
  }

  // --- Account deletion ---
  let deleteOpen = $state(false);
  let deleteConfirm = $state('');
  let deleting = $state(false);
  let deleteError = $state(/** @type {string | null} */ (null));
  const canDelete = $derived(deleteConfirm.trim().toUpperCase() === 'DELETE');

  async function doDelete() {
    if (deleting || !canDelete) return;
    deleting = true;
    deleteError = null;
    try {
      await deleteMyAccount();
      // Drop local auth state and leave for the landing page.
      await logout().catch(() => {});
      await goto('/', { replaceState: true });
    } catch (err) {
      deleteError = err instanceof Error ? err.message : 'Could not delete your account.';
      deleting = false;
    }
  }
</script>

<section class="space-y-8">
  <header>
    <p
      class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
    >
      <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
      Account
    </p>
    <h1 class="mt-3 text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
      Your account
    </h1>
  </header>

  {#if !ready}
    <p class="text-sm text-canvas-muted">Loading…</p>
  {:else}
    <!-- Profile -->
    <div class="card space-y-4 p-6 sm:p-8" in:fade={reduced({ duration: 200 })}>
      <div>
        <p class="text-xs uppercase tracking-wide text-canvas-muted">Profile</p>
        <p class="mt-1 text-sm text-canvas-muted">Signed in as {user?.email}</p>
      </div>
      <div class="space-y-1.5">
        <label class="label" for="acct-name">What should we call you?</label>
        <div class="flex items-center gap-2">
          <input
            id="acct-name"
            type="text"
            class="field flex-1"
            bind:value={nameDraft}
            placeholder={greetingName(user)}
            maxlength="120"
          />
          <button type="button" class="btn-primary" onclick={saveName} disabled={nameSaving}>
            {nameSaving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>

    <!-- Plan -->
    <div class="card space-y-4 p-6 sm:p-8">
      <div class="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p class="text-xs uppercase tracking-wide text-canvas-muted">Plan</p>
          <p class="mt-1 text-2xl font-semibold text-canvas-ink">{planLabel}</p>
        </div>
        <a href="/billing" class="btn-ghost">Billing &amp; plans</a>
      </div>

      {#if planMessage}
        <p
          class="flex items-center gap-2 rounded-xl bg-healthy-50 px-3 py-2 text-sm text-healthy-700"
          in:fly={reduced({ y: 4, duration: 200, easing: quintOut })}
        >
          <span aria-hidden="true">✓</span>{planMessage}
        </p>
      {/if}
      {#if planError}
        <p class="rounded-xl bg-action-50 px-3 py-2 text-sm text-action-700">{planError}</p>
      {/if}

      {#if isFree}
        <p class="text-sm text-canvas-muted">
          You're on the free plan. Upgrade any time for weekly auto-audits, competitor tracking and
          the Monday digest.
        </p>
        <a href="/billing" class="btn-primary inline-flex">See plans</a>
      {:else}
        <div class="flex flex-wrap gap-3">
          {#if isMax}
            <button type="button" class="btn-ghost" onclick={downgradeToPro} disabled={planBusy}>
              {planBusy ? 'Working…' : 'Switch to Pro'}
            </button>
          {/if}
          {#if confirmingCancel}
            <div
              class="flex w-full flex-col gap-3 rounded-2xl border border-action-100 bg-action-50/60 p-4 sm:flex-row sm:items-center sm:justify-between"
              in:fade={reduced({ duration: 160 })}
            >
              <p class="text-sm text-canvas-ink">
                Cancel your subscription? You'll keep access until the period ends, then drop to
                Free.
              </p>
              <div class="flex gap-2">
                <button
                  type="button"
                  class="btn-ghost"
                  onclick={() => (confirmingCancel = false)}
                  disabled={planBusy}
                >
                  Keep plan
                </button>
                <button
                  type="button"
                  class="inline-flex min-h-[40px] items-center justify-center rounded-xl bg-action-500 px-4 text-sm font-medium text-white transition hover:bg-action-600 disabled:opacity-60"
                  onclick={doCancel}
                  disabled={planBusy}
                >
                  {planBusy ? 'Cancelling…' : 'Yes, cancel'}
                </button>
              </div>
            </div>
          {:else}
            <button type="button" class="btn-ghost" onclick={() => (confirmingCancel = true)}>
              Cancel subscription
            </button>
          {/if}
        </div>
      {/if}
    </div>

    <!-- Notifications (paid tiers only — the digest is a paid feature) -->
    {#if !isFree}
      <div class="card space-y-4 p-6 sm:p-8">
        <p class="text-xs uppercase tracking-wide text-canvas-muted">Notifications</p>

        <!-- Weekly digest email -->
        <div class="flex flex-wrap items-center justify-between gap-3">
          <div>
            <p class="text-sm font-medium text-canvas-ink">Weekly digest email</p>
            <p class="text-xs text-canvas-muted">
              A Monday summary of what changed across your businesses.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-label="Weekly digest email"
            aria-checked={user?.weekly_digest_enabled ? 'true' : 'false'}
            onclick={toggleDigest}
            disabled={digestSaving}
            class={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors duration-200 ${
              user?.weekly_digest_enabled ? 'bg-healthy-500' : 'bg-canvas-soft'
            }`}
          >
            <span
              class={`inline-block h-5 w-5 transform rounded-full bg-white shadow-sm transition-transform duration-200 ${
                user?.weekly_digest_enabled ? 'translate-x-6' : 'translate-x-1'
              }`}
            ></span>
          </button>
        </div>

        {#if pushSupported && pushAvailable}
          <hr class="border-canvas-soft" />
          <!-- Push notifications (this device) -->
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p class="text-sm font-medium text-canvas-ink">Push notifications</p>
              <p class="text-xs text-canvas-muted">
                A nudge on this device when a scheduled audit lands or a competitor moves.
              </p>
              {#if pushError}
                <p class="mt-1 text-xs text-action-700">{pushError}</p>
              {/if}
            </div>
            <button
              type="button"
              role="switch"
              aria-label="Push notifications"
              aria-checked={pushSubscribed ? 'true' : 'false'}
              onclick={togglePush}
              disabled={pushBusy}
              class={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors duration-200 ${
                pushSubscribed ? 'bg-healthy-500' : 'bg-canvas-soft'
              }`}
            >
              <span
                class={`inline-block h-5 w-5 transform rounded-full bg-white shadow-sm transition-transform duration-200 ${
                  pushSubscribed ? 'translate-x-6' : 'translate-x-1'
                }`}
              ></span>
            </button>
          </div>
        {/if}
      </div>
    {/if}

    <!-- Your data -->
    <div class="card space-y-4 p-6 sm:p-8">
      <p class="text-xs uppercase tracking-wide text-canvas-muted">Your data</p>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p class="text-sm font-medium text-canvas-ink">Download your data</p>
          <p class="text-xs text-canvas-muted">
            Everything we hold for you — businesses, audits, recommendations — as a JSON file.
          </p>
        </div>
        <button type="button" class="btn-ghost" onclick={downloadData} disabled={exporting}>
          {exporting ? 'Preparing…' : 'Download'}
        </button>
      </div>

      <hr class="border-canvas-soft" />

      <div class="space-y-3">
        <div>
          <p class="text-sm font-medium text-action-700">Delete account</p>
          <p class="text-xs text-canvas-muted">
            Permanently removes your account and all its data. This can't be undone.
          </p>
        </div>
        {#if !deleteOpen}
          <button
            type="button"
            class="rounded-xl border border-action-200 px-4 py-2 text-sm font-medium text-action-700 transition hover:bg-action-50"
            onclick={() => (deleteOpen = true)}
          >
            Delete my account
          </button>
        {:else}
          <div
            class="space-y-3 rounded-2xl border border-action-100 bg-action-50/50 p-4"
            in:fade={reduced({ duration: 160 })}
          >
            <label class="block text-xs text-canvas-ink" for="delete-confirm">
              Type <strong>DELETE</strong> to confirm.
            </label>
            <input
              id="delete-confirm"
              type="text"
              class="field"
              bind:value={deleteConfirm}
              autocomplete="off"
              autocapitalize="characters"
              placeholder="DELETE"
            />
            {#if deleteError}
              <p class="text-xs text-action-700">{deleteError}</p>
            {/if}
            <div class="flex gap-2">
              <button
                type="button"
                class="btn-ghost"
                onclick={() => {
                  deleteOpen = false;
                  deleteConfirm = '';
                  deleteError = null;
                }}
                disabled={deleting}
              >
                Cancel
              </button>
              <button
                type="button"
                class="inline-flex min-h-[40px] items-center justify-center rounded-xl bg-action-500 px-4 text-sm font-medium text-white transition hover:bg-action-600 disabled:opacity-50"
                onclick={doDelete}
                disabled={!canDelete || deleting}
              >
                {deleting ? 'Deleting…' : 'Permanently delete'}
              </button>
            </div>
          </div>
        {/if}
      </div>
    </div>

    <!-- Legal & policies -->
    <div class="card space-y-3 p-6 sm:p-8">
      <p class="text-xs uppercase tracking-wide text-canvas-muted">Legal &amp; policies</p>
      <div class="divide-y divide-canvas-soft">
        <a
          href="/privacy"
          class="flex items-center justify-between py-3 text-sm text-canvas-ink hover:text-healthy-700"
        >
          Privacy Policy <span class="text-canvas-muted">→</span>
        </a>
        <a
          href="/terms"
          class="flex items-center justify-between py-3 text-sm text-canvas-ink hover:text-healthy-700"
        >
          Terms of Service <span class="text-canvas-muted">→</span>
        </a>
        <a
          href="/refund"
          class="flex items-center justify-between py-3 text-sm text-canvas-ink hover:text-healthy-700"
        >
          Refund Policy <span class="text-canvas-muted">→</span>
        </a>
      </div>
    </div>

    <!-- Support -->
    <div class="card flex flex-wrap items-center justify-between gap-3 p-6 sm:p-8">
      <div>
        <p class="text-xs uppercase tracking-wide text-canvas-muted">Support</p>
        <p class="mt-1 text-sm font-medium text-canvas-ink">Need a hand?</p>
        <p class="text-xs text-canvas-muted">We read every message.</p>
      </div>
      <a class="btn-ghost" href={`mailto:${supportEmail}`}>Contact us</a>
    </div>

    <!-- About -->
    <div class="card p-6 sm:p-8">
      <p class="text-xs uppercase tracking-wide text-canvas-muted">About</p>
      <p class="mt-1 text-sm text-canvas-ink">AuditHealth · v{appVersion}</p>
      <p class="mt-1 text-xs text-canvas-muted">A calm dashboard for your business's online presence.</p>
    </div>
  {/if}
</section>
