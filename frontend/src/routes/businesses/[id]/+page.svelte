<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';

  let status = $state(/** @type {'loading' | 'no_audit' | 'error'} */ ('loading'));
  let errorMessage = $state(/** @type {string | null} */ (null));

  const businessId = $derived(parseInt($page.params.id ?? '', 10));

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user) {
      await goto('/login', { replaceState: true });
      return;
    }

    try {
      const res = await fetch(`/api/businesses/${businessId}/latest-audit`, {
        credentials: 'same-origin'
      });
      if (res.status === 404) {
        // 404 here can mean two things: the business doesn't belong to this
        // user (treated as not-found), or no completed audit yet. Either
        // way, show the "kick off an audit" affordance — the home form is
        // the canonical entry point for the second case, and the first case
        // shouldn't happen via the UI.
        status = 'no_audit';
        return;
      }
      if (!res.ok) throw new Error(`Couldn't load this business (${res.status})`);
      const audit = await res.json();
      await goto(`/audits/${audit.audit_id}/dashboard`, { replaceState: true });
    } catch (err) {
      status = 'error';
      errorMessage = err instanceof Error ? err.message : 'Could not load this business.';
    }
  });
</script>

<section class="mx-auto max-w-md text-center">
  {#if status === 'loading'}
    <p class="text-sm text-canvas-muted">Pulling up your latest audit…</p>
  {:else if status === 'no_audit'}
    <div class="card p-6 sm:p-8">
      <p class="text-2xl">🪴</p>
      <h1 class="mt-3 text-lg font-semibold text-canvas-ink">No health check yet</h1>
      <p class="mt-2 text-sm text-canvas-muted">
        We haven't run a check for this business yet. Kick one off from the home page.
      </p>
      <a class="btn-primary mt-4" href="/">Run a health check</a>
    </div>
  {:else if status === 'error'}
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">{errorMessage}</p>
      <a href="/dashboard" class="btn-ghost mt-3 inline-flex text-action-700">
        ← Back to your businesses
      </a>
    </div>
  {/if}
</section>
