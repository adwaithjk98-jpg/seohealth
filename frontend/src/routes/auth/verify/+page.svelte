<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';

  import { verifyMagicLink } from '$lib/auth.svelte.js';

  let status = $state(/** @type {'verifying' | 'failed'} */ ('verifying'));
  let errorMessage = $state(/** @type {string | null} */ (null));
  // Show a softer "still working on it…" line if verification takes a beat
  // longer than usual, so the page never reads as frozen (M5).
  let slow = $state(false);

  onMount(async () => {
    const token = $page.url.searchParams.get('token');
    if (!token) {
      status = 'failed';
      errorMessage = 'This sign-in link is missing its token.';
      return;
    }

    const slowTimer = setTimeout(() => {
      slow = true;
    }, 2500);

    try {
      await verifyMagicLink(token);
      // Use a full reload (not SvelteKit's client-side ``goto``) so the
      // dashboard's ``+page.js`` loader re-runs fresh and includes the
      // session cookie we just set. Client-side navigation reused a
      // cached loader result that pre-dated the cookie, which 401-ed
      // and bounced the user back to /login (a "logs in, then logs
      // out a second later" flicker on slower networks and on the
      // first sign-in over Cloudflare Tunnel).
      window.location.replace('/dashboard');
    } catch (err) {
      status = 'failed';
      errorMessage =
        err instanceof Error ? err.message : 'This sign-in link is invalid or has expired.';
    } finally {
      clearTimeout(slowTimer);
    }
  });
</script>

<section class="mx-auto mt-10 max-w-md text-center">
  {#if status === 'verifying'}
    <div class="card p-8">
      <div class="mx-auto h-10 w-10 animate-spin rounded-full border-2 border-healthy-200 border-t-healthy-600"></div>
      <p class="mt-4 text-base font-medium text-canvas-ink">
        <span aria-hidden="true">✉️</span> Signing you in…
      </p>
      <p class="mt-1 text-xs text-canvas-muted">
        {#if slow}
          Almost there — just a moment longer.
        {:else}
          Hang tight, this takes a second.
        {/if}
      </p>
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
