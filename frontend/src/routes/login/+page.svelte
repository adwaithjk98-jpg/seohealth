<script>
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { fade } from 'svelte/transition';

  import { authState, loadCurrentUser, requestMagicLink } from '$lib/auth.svelte.js';

  let email = $state('');
  let submitting = $state(false);
  let sent = $state(false);
  let errorMessage = $state(/** @type {string | null} */ (null));

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (authState.user) await goto('/dashboard');
  });

  const canSubmit = $derived(!submitting && email.trim().length > 3);

  /** @param {SubmitEvent} event */
  async function handleSubmit(event) {
    event.preventDefault();
    if (!canSubmit) return;
    submitting = true;
    errorMessage = null;
    try {
      await requestMagicLink(email.trim());
      sent = true;
    } catch (err) {
      errorMessage =
        err instanceof Error ? err.message : 'Could not send your sign-in link.';
    } finally {
      submitting = false;
    }
  }

  function tryAgain() {
    sent = false;
    errorMessage = null;
  }
</script>

<section class="mx-auto max-w-md">
  <header class="text-center">
    <p
      class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
    >
      <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
      Sign in
    </p>
    <h1 class="mt-3 text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
      Welcome back
    </h1>
    <p class="mt-2 text-sm text-canvas-muted">
      No passwords here. We'll email you a one-tap sign-in link.
    </p>
  </header>

  <div class="card mt-8 p-6 sm:p-8">
    {#if !sent}
      <form class="space-y-4" onsubmit={handleSubmit}>
        <div class="space-y-2">
          <label class="label" for="login-email">Email</label>
          <input
            id="login-email"
            type="email"
            class="field"
            placeholder="you@example.com"
            autocomplete="email"
            inputmode="email"
            required
            bind:value={email}
          />
        </div>

        {#if errorMessage}
          <p class="rounded-xl bg-action-50 px-3 py-2 text-sm text-action-700">{errorMessage}</p>
        {/if}

        <button type="submit" class="btn-primary w-full" disabled={!canSubmit}>
          {#if submitting}Sending your link…{:else}Email me a sign-in link{/if}
        </button>

        <p class="text-center text-xs text-canvas-muted">
          We'll create your account if it's your first time.
        </p>
      </form>
    {:else}
      <div class="space-y-4 text-center" in:fade={{ duration: 250 }}>
        <div class="mx-auto grid h-12 w-12 place-items-center rounded-2xl bg-healthy-50 text-2xl">
          ✉️
        </div>
        <h2 class="text-lg font-semibold text-canvas-ink">Check your inbox</h2>
        <p class="text-sm text-canvas-muted">
          If <span class="font-medium text-canvas-ink">{email}</span> is registered, a sign-in
          link is on its way. The link is good for the next 15 minutes.
        </p>
        <p class="rounded-xl bg-canvas-soft px-3 py-2 text-xs text-canvas-muted">
          Local dev: the link is printed in the backend terminal — copy it and paste it into your
          browser.
        </p>
        <button type="button" class="btn-ghost w-full" onclick={tryAgain}>
          Use a different email
        </button>
      </div>
    {/if}
  </div>
</section>
