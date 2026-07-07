<script>
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { fade } from 'svelte/transition';

  import { authState, loadCurrentUser, requestMagicLink } from '$lib/auth.svelte.js';

  // Vite injects `import.meta.env.DEV` at build time. We use it to show a
  // local-dev hint ("link is in the backend terminal") that would only confuse
  // production users.
  const isDev = import.meta.env.DEV;

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
      // Backend returns HTTP 500 with a friendly `detail` message when Resend
      // delivery fails; readJsonError surfaces that as err.message. Fall back
      // to a generic line if anything else went wrong (network, etc).
      const raw = err instanceof Error ? err.message : '';
      errorMessage = raw && !raw.startsWith('Request failed')
        ? raw
        : "We couldn't send your sign-in email. Please check your address and try again.";
    } finally {
      submitting = false;
    }
  }

  function tryAgain() {
    sent = false;
    errorMessage = null;
  }
</script>

<svelte:head><title>Sign in · SEO Health</title></svelte:head>

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
          <div
            class="flex items-start gap-2 rounded-xl bg-action-50 px-3 py-2 text-sm text-action-700"
            role="alert"
            in:fade={{ duration: 150 }}
          >
            <span aria-hidden="true">⚠️</span>
            <span>{errorMessage}</span>
          </div>
        {/if}

        <button type="submit" class="btn-primary w-full" disabled={!canSubmit}>
          {#if submitting}
            <span class="inline-flex items-center justify-center gap-2">
              <span
                class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                aria-hidden="true"
              ></span>
              Sending your link…
            </span>
          {:else}
            Email me a sign-in link
          {/if}
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
        <h2 class="text-lg font-semibold text-canvas-ink">Check your email!</h2>
        <p class="text-sm text-canvas-muted">
          If <span class="font-medium text-canvas-ink">{email}</span> is registered, a sign-in
          link is on its way. The link is good for the next 15 minutes.
        </p>
        <p class="text-xs text-canvas-muted">
          Don't see it? Check your spam folder, or
          <button type="button" class="font-medium text-healthy-700 underline" onclick={tryAgain}>
            try a different email
          </button>.
        </p>
        {#if isDev}
          <p class="rounded-xl bg-canvas-soft px-3 py-2 text-xs text-canvas-muted">
            <span class="font-medium">Dev tip:</span> if no Resend API key is configured, the
            link is printed in the backend terminal — copy and paste it into your browser.
          </p>
        {/if}
        <button type="button" class="btn-ghost w-full" onclick={tryAgain}>
          Use a different email
        </button>
      </div>
    {/if}
  </div>
</section>
