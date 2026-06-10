<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';
  import { page } from '$app/stores';
  import { goto, onNavigate } from '$app/navigation';
  import { prefersReducedMotion } from '$lib/motion.js';

  // Smooth crossfade between routes via the View Transitions API. Graceful
  // no-op on browsers without it; skipped under reduced motion (app.css also
  // disables the animation as a belt-and-suspenders). ~200ms to match the
  // app's interaction timings.
  onNavigate((navigation) => {
    // @ts-ignore — startViewTransition isn't in the default lib.dom types yet
    if (typeof document === 'undefined' || !document.startViewTransition) return;
    if (prefersReducedMotion()) return;
    return new Promise((resolve) => {
      // @ts-ignore
      document.startViewTransition(async () => {
        resolve();
        await navigation.complete;
      });
    });
  });

  import {
    authState,
    loadCurrentUser,
    logout,
    isPublicRoute,
    updateCurrentUser,
    greetingName
  } from '$lib/auth.svelte.js';

  let { children } = $props();
  let mobileMenuOpen = $state(false);
  let nameDraft = $state('');
  let nameSaving = $state(false);
  let nameError = $state(/** @type {string | null} */ (null));

  // Network status — drives a calm offline banner. The service worker still
  // serves cached views, so "offline" is informational, not a dead end.
  let online = $state(true);
  $effect(() => {
    online = navigator.onLine;
    const on = () => (online = true);
    const off = () => (online = false);
    window.addEventListener('online', on);
    window.addEventListener('offline', off);
    return () => {
      window.removeEventListener('online', on);
      window.removeEventListener('offline', off);
    };
  });

  // The single persistent upgrade affordance lives in the account area and is
  // free-only. Never a banner, never animated — just always quietly there.
  const tier = $derived(
    authState.user?.subscription_state?.tier ?? authState.user?.plan ?? 'free'
  );
  const isFree = $derived(tier === 'free');
  const isAdmin = $derived(authState.user?.is_admin === true);

  $effect(() => {
    // Seed the input whenever the menu opens or the signed-in user changes.
    if (mobileMenuOpen) {
      nameDraft = authState.user?.display_name ?? '';
      nameError = null;
    }
  });

  async function handleSaveDisplayName() {
    if (nameSaving) return;
    const next = nameDraft.trim();
    if ((authState.user?.display_name ?? '') === next) {
      // No-op save — close menu without a round-trip.
      mobileMenuOpen = false;
      return;
    }
    nameSaving = true;
    nameError = null;
    try {
      await updateCurrentUser({ display_name: next });
      mobileMenuOpen = false;
    } catch (err) {
      nameError = err instanceof Error ? err.message : "Couldn't save your name.";
    } finally {
      nameSaving = false;
    }
  }

  onMount(async () => {
    if (!authState.loaded) {
      await loadCurrentUser();
    }
    enforceGate($page.url.pathname);
  });

  // Re-evaluate the gate whenever the route or the loaded user changes.
  $effect(() => {
    if (!authState.loaded) return;
    enforceGate($page.url.pathname);
    // Auto-close the mobile account menu whenever the route changes, so
    // tapping a nav link doesn't leave a stale popover open over the new page.
    mobileMenuOpen = false;
  });

  /** @param {string} pathname */
  function enforceGate(pathname) {
    // Home is public — the form there nudges signed-out users to /login.
    // Everything else (dashboard, audits) requires a session.
    if (pathname === '/' || isPublicRoute(pathname)) return;
    if (!authState.user) {
      goto('/login', { replaceState: true });
    }
  }

  async function handleLogout() {
    mobileMenuOpen = false;
    await logout();
  }
</script>

<div class="min-h-screen bg-canvas">
  <header
    class="sticky top-0 z-30 border-b border-canvas-soft bg-canvas/85 backdrop-blur"
    style="padding-top: env(safe-area-inset-top);"
  >
    <div class="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3 sm:px-6 sm:py-4">
      <a href="/" class="flex min-w-0 items-center gap-2">
        <span
          class="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-healthy-500 text-white shadow-soft"
          aria-hidden="true"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="h-4 w-4"
          >
            <path d="M21 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
        </span>
        <span class="truncate text-sm font-semibold tracking-tight sm:text-base">
          <span class="sm:hidden">SEO Health</span>
          <span class="hidden sm:inline">Local SEO Health</span>
        </span>
      </a>

      <nav class="flex items-center gap-1 text-sm sm:gap-1.5">
        {#if authState.user}
          <!-- Dedicated home affordance. The logo top-left is also a link
               home but reads as branding; this gives a glanceable "go to
               workspace" target whether the user is on a deep audit
               page, a billing page, or a single-business view. -->
          <a
            class="btn-ghost grid h-9 w-9 place-items-center"
            href="/dashboard"
            aria-label="Go to dashboard"
            title="Dashboard"
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
              aria-hidden="true"
            >
              <path d="M3 10.5 12 3l9 7.5" />
              <path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5" />
            </svg>
          </a>
          {#if isFree}
            <!-- Quiet, persistent Free -> Pro entry. Static; no animation. -->
            <a
              class="hidden items-center rounded-full border border-healthy-200 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700 transition-colors hover:bg-healthy-100 sm:inline-flex"
              href="/billing"
            >
              Upgrade to Pro
            </a>
          {/if}
          {#if isAdmin}
            <a class="btn-ghost hidden sm:inline-flex" href="/admin">Stats</a>
          {/if}
          <a class="btn-ghost hidden sm:inline-flex" href="/account">Account</a>
          <a class="btn-ghost hidden sm:inline-flex" href="/billing">Billing</a>
          <span class="hidden text-xs text-canvas-muted sm:inline" title={authState.user.email}>
            {greetingName(authState.user)}
          </span>
          <button
            type="button"
            class="btn-ghost hidden sm:inline-flex"
            onclick={handleLogout}
          >
            Sign out
          </button>

          <!-- m7 — mobile-only popover so the signed-in email + sign-out
               are still reachable below 768px (previously the email just
               disappeared from the header with no replacement). -->
          <div class="relative sm:hidden">
            <button
              type="button"
              class="btn-ghost grid h-9 w-9 place-items-center"
              aria-haspopup="menu"
              aria-expanded={mobileMenuOpen}
              aria-label="Account menu"
              onclick={() => (mobileMenuOpen = !mobileMenuOpen)}
            >
              <span
                class="grid h-7 w-7 place-items-center rounded-full bg-healthy-500 text-xs font-semibold uppercase text-white"
                aria-hidden="true"
              >
                {greetingName(authState.user)[0] || authState.user.email[0]}
              </span>
            </button>
            {#if mobileMenuOpen}
              <!-- Backdrop tap closes the popover without taking up screen
                   real-estate on small viewports. -->
              <button
                type="button"
                class="fixed inset-0 z-30 cursor-default bg-canvas-ink/0"
                aria-hidden="true"
                tabindex="-1"
                onclick={() => (mobileMenuOpen = false)}
              ></button>
              <div
                class="absolute right-0 top-12 z-40 w-72 rounded-2xl border border-canvas-soft bg-white p-3 shadow-soft"
                role="menu"
                transition:fly={{ y: -8, duration: 180, easing: quintOut }}
              >
                <label class="px-2 text-xs uppercase tracking-wide text-canvas-muted" for="display-name-input">
                  What should we call you?
                </label>
                <div class="mt-1.5 flex items-center gap-2 px-2">
                  <input
                    id="display-name-input"
                    type="text"
                    bind:value={nameDraft}
                    placeholder={greetingName(authState.user)}
                    maxlength="120"
                    class="flex-1 rounded-xl border border-canvas-soft bg-canvas-soft/50 px-3 py-2 text-sm text-canvas-ink placeholder:text-canvas-muted focus:border-healthy-300 focus:bg-white focus:outline-none"
                    onkeydown={(e) => e.key === 'Enter' && handleSaveDisplayName()}
                  />
                  <button
                    type="button"
                    class="rounded-xl bg-healthy-500 px-3 py-2 text-xs font-medium text-white hover:bg-healthy-600 disabled:opacity-50"
                    onclick={handleSaveDisplayName}
                    disabled={nameSaving}
                  >
                    {nameSaving ? '…' : 'Save'}
                  </button>
                </div>
                {#if nameError}
                  <p class="mt-2 px-2 text-xs text-action-700">{nameError}</p>
                {/if}
                <p class="mt-2 truncate px-2 text-xs text-canvas-muted">
                  Signed in as {authState.user.email}
                </p>
                {#if isFree}
                  <a
                    href="/billing"
                    class="btn-ghost mt-2 w-full justify-start font-medium text-healthy-700"
                    role="menuitem"
                  >
                    Upgrade to Pro
                  </a>
                {/if}
                {#if isAdmin}
                  <a
                    href="/admin"
                    class="btn-ghost mt-2 w-full justify-start"
                    role="menuitem"
                  >
                    Stats
                  </a>
                {/if}
                <a
                  href="/account"
                  class="btn-ghost mt-2 w-full justify-start"
                  role="menuitem"
                >
                  Account
                </a>
                <a
                  href="/billing"
                  class="btn-ghost mt-2 w-full justify-start"
                  role="menuitem"
                >
                  Billing &amp; plan
                </a>
                <button
                  type="button"
                  class="btn-ghost mt-2 w-full justify-start"
                  onclick={handleLogout}
                >
                  Sign out
                </button>
              </div>
            {/if}
          </div>
        {:else if authState.loaded}
          <a class="btn-ghost" href="/login">Sign in</a>
        {/if}
      </nav>
    </div>
  </header>

  {#if !online}
    <div
      class="bg-attention-100 px-4 py-2 text-center text-xs font-medium text-attention-700"
      role="status"
      aria-live="polite"
      transition:fly={{ y: -8, duration: 200, easing: quintOut }}
    >
      You're offline — showing your last loaded view. We'll catch up when you're back.
    </div>
  {/if}

  <main class="mx-auto max-w-5xl px-4 py-6 sm:px-6 sm:py-10">
    {@render children()}
  </main>

  <footer
    class="mx-auto flex max-w-5xl flex-col gap-2 px-4 pb-10 pt-6 text-xs text-canvas-muted sm:flex-row sm:items-center sm:justify-between sm:px-6"
  >
    <span>A calm dashboard for your business's online presence.</span>
    <nav class="flex flex-wrap gap-x-4 gap-y-1">
      <a class="hover:text-canvas-ink" href="/privacy">Privacy</a>
      <a class="hover:text-canvas-ink" href="/terms">Terms</a>
      <a class="hover:text-canvas-ink" href="/refund">Refund</a>
    </nav>
  </footer>
</div>
