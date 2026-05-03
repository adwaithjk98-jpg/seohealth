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
          <button type="button" class="btn-ghost" onclick={handleLogout}>Sign out</button>
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
