<script>
  import '../app.css';
  import { onMount } from 'svelte';
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';

  import {
    authState,
    loadCurrentUser,
    logout,
    isPublicRoute
  } from '$lib/auth.svelte.js';

  let { children } = $props();
  let mobileMenuOpen = $state(false);

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
  <header class="border-b border-canvas-soft bg-canvas/80 backdrop-blur">
    <div class="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
      <a href="/" class="flex items-center gap-2">
        <span
          class="grid h-8 w-8 place-items-center rounded-xl bg-healthy-500 text-white shadow-soft"
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
        <span class="text-base font-semibold tracking-tight">Local SEO Health</span>
      </a>

      <nav class="flex items-center gap-1 text-sm">
        <a class="btn-ghost" href="/">Home</a>
        {#if authState.user}
          <a class="btn-ghost" href="/dashboard">Dashboard</a>
          <span class="hidden text-xs text-canvas-muted sm:inline">{authState.user.email}</span>
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
                {authState.user.email[0]}
              </span>
            </button>
            {#if mobileMenuOpen}
              <div
                class="absolute right-0 top-12 z-40 w-60 rounded-2xl border border-canvas-soft bg-white p-3 shadow-soft"
                role="menu"
              >
                <p class="px-2 text-xs uppercase tracking-wide text-canvas-muted">
                  Signed in as
                </p>
                <p class="mt-0.5 truncate px-2 text-sm font-medium text-canvas-ink">
                  {authState.user.email}
                </p>
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

  <main class="mx-auto max-w-5xl px-6 py-10">
    {@render children()}
  </main>

  <footer class="mx-auto max-w-5xl px-6 pb-10 pt-6 text-xs text-canvas-muted">
    A calm dashboard for your business's online presence.
  </footer>
</div>
