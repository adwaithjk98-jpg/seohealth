<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';

  let businesses = $state(/** @type {any[]} */ ([]));
  let loading = $state(true);
  let errorMessage = $state(/** @type {string | null} */ (null));

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user) {
      await goto('/login', { replaceState: true });
      return;
    }
    try {
      const res = await fetch('/api/businesses', { credentials: 'same-origin' });
      if (!res.ok) throw new Error(`Couldn't load your businesses (${res.status})`);
      businesses = await res.json();
    } catch (err) {
      errorMessage = err instanceof Error ? err.message : 'Could not load your businesses.';
    } finally {
      loading = false;
    }
  });
</script>

<section class="space-y-8">
  <header>
    <p
      class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
    >
      <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
      Your businesses
    </p>
    <h1 class="mt-3 text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
      Welcome back{#if authState.user}, <span class="text-healthy-600">{authState.user.email}</span>{/if}
    </h1>
    <p class="mt-2 text-sm text-canvas-muted">
      Pick a business to see its latest health check, or add a new one.
    </p>
  </header>

  {#if loading}
    <p class="text-sm text-canvas-muted">Loading your businesses…</p>
  {:else if errorMessage}
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">{errorMessage}</p>
    </div>
  {:else if businesses.length === 0}
    <div class="card flex flex-col items-start gap-4 p-6 sm:p-8">
      <p class="text-2xl">👋</p>
      <h2 class="text-lg font-semibold text-canvas-ink">No businesses yet</h2>
      <p class="text-sm text-canvas-muted">
        Add your first business and we'll run a free health check right away.
      </p>
      <a class="btn-primary" href="/">Add a business</a>
    </div>
  {:else}
    <div class="grid gap-4 sm:grid-cols-2">
      {#each businesses as biz, i (biz.id)}
        <a
          href={`/businesses/${biz.id}`}
          class="card flex flex-col gap-2 p-5 transition hover:border-canvas-muted/30 hover:shadow-soft"
          in:fly={{ y: 12, delay: 60 * i, duration: 320, easing: quintOut }}
        >
          <p class="text-base font-semibold text-canvas-ink">{biz.name}</p>
          <p class="text-xs text-canvas-muted">{biz.city} · {biz.country}</p>
          <span class="mt-2 inline-flex items-center gap-1 text-xs font-medium text-healthy-700">
            See latest health check →
          </span>
        </a>
      {/each}
    </div>
    <div>
      <a class="btn-ghost" href="/">+ Add another business</a>
    </div>
  {/if}
</section>
