<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';

  import { verifyMagicLink } from '$lib/auth.svelte.js';

  let status = $state(/** @type {'verifying' | 'failed'} */ ('verifying'));
  let errorMessage = $state(/** @type {string | null} */ (null));

  onMount(async () => {
    const token = $page.url.searchParams.get('token');
    if (!token) {
      status = 'failed';
      errorMessage = 'This sign-in link is missing its token.';
      return;
    }
    try {
      await verifyMagicLink(token);
      // Replace history so the back button doesn't bounce back to a now-used token.
      await goto('/dashboard', { replaceState: true });
    } catch (err) {
      status = 'failed';
      errorMessage =
        err instanceof Error ? err.message : 'This sign-in link is invalid or has expired.';
    }
  });
</script>

<section class="mx-auto mt-10 max-w-md text-center">
  {#if status === 'verifying'}
    <div class="card p-8">
      <div class="mx-auto h-8 w-8 animate-spin rounded-full border-2 border-healthy-200 border-t-healthy-600"></div>
      <p class="mt-4 text-sm text-canvas-muted">Signing you in…</p>
    </div>
  {:else}
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">We couldn't sign you in.</p>
      <p class="mt-1">{errorMessage}</p>
      <a href="/login" class="btn-ghost mt-4 inline-flex text-action-700">
        ← Back to sign in
      </a>
    </div>
  {/if}
</section>
