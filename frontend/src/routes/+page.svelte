<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';

  let mode = $state(/** @type {'name' | 'url'} */ ('name'));
  let businessName = $state('');
  let city = $state('');
  let mapsUrl = $state('');
  let submitting = $state(false);
  let errorMessage = $state(/** @type {string | null} */ (null));

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
  });

  const canSubmit = $derived(
    !submitting &&
      authState.user &&
      (mode === 'name'
        ? businessName.trim().length > 0 && city.trim().length > 0
        : mapsUrl.trim().length > 0)
  );

  async function handleSubmit(event) {
    event.preventDefault();
    if (!canSubmit) return;

    submitting = true;
    errorMessage = null;

    try {
      const businessPayload =
        mode === 'name'
          ? { name: businessName.trim(), city: city.trim() }
          : { maps_url: mapsUrl.trim() };

      const business = await postJson('/api/businesses', businessPayload);
      const audit = await postJson('/api/audits', { business_id: business.id });
      await goto(`/audits/${audit.audit_id}`);
    } catch (err) {
      // 401 from backend (e.g. session expired between page load and submit)
      // → bounce to login.
      if (err instanceof Error && /401/.test(err.message)) {
        await goto('/login');
        return;
      }
      errorMessage =
        err instanceof Error ? err.message : 'Something went wrong starting your audit.';
      submitting = false;
    }
  }

  async function postJson(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(body)
    });
    if (!res.ok) {
      const detail = await safeJsonError(res);
      throw new Error(detail);
    }
    return res.json();
  }

  async function safeJsonError(res) {
    try {
      const data = await res.json();
      if (typeof data?.detail === 'string') return data.detail;
      if (Array.isArray(data?.detail) && data.detail[0]?.msg) return data.detail[0].msg;
    } catch {
      // fall through
    }
    return `Request failed (${res.status})`;
  }
</script>

<section class="grid gap-10 lg:grid-cols-[1.1fr_1fr] lg:items-center">
  <div>
    <p
      class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
    >
      <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
      Free during the beta
    </p>
    <h1 class="mt-4 text-4xl font-semibold tracking-tight text-canvas-ink sm:text-5xl">
      Let's give your business a quick health check.
    </h1>
    <p class="mt-4 max-w-xl text-base leading-relaxed text-canvas-muted">
      We'll quietly look at your Google Maps listing, your website, and your Instagram, then walk you
      through the next concrete thing to improve. No jargon, no overwhelm.
    </p>

    <ul class="mt-6 space-y-2 text-sm text-canvas-ink">
      <li class="flex items-start gap-2">
        <span class="mt-1 h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
        Plain-English findings, not auditor-speak
      </li>
      <li class="flex items-start gap-2">
        <span class="mt-1 h-1.5 w-1.5 rounded-full bg-attention-500"></span>
        One clear next action at all times
      </li>
      <li class="flex items-start gap-2">
        <span class="mt-1 h-1.5 w-1.5 rounded-full bg-action-500"></span>
        Tracked over time so you can see progress
      </li>
    </ul>
  </div>

  <div class="card p-6 sm:p-8">
    <h2 class="text-lg font-semibold text-canvas-ink">Add your business</h2>
    <p class="mt-1 text-sm text-canvas-muted">
      Tell us how to find you. We'll handle the rest.
    </p>

    {#if authState.loaded && !authState.user}
      <div class="mt-5 rounded-2xl border border-healthy-100 bg-healthy-50/60 p-4 text-sm text-canvas-ink">
        <p class="font-medium">Sign in first</p>
        <p class="mt-1 text-canvas-muted">
          We'll keep your audits tied to your email so you can come back to your dashboard
          anytime.
        </p>
        <a href="/login" class="btn-primary mt-3 w-full">Sign in to continue</a>
      </div>
    {/if}

    <div class="mt-5 inline-flex rounded-xl bg-canvas-soft p-1 text-sm">
      <button
        type="button"
        class={`rounded-lg px-3 py-1.5 transition ${
          mode === 'name'
            ? 'bg-white text-canvas-ink shadow-soft'
            : 'text-canvas-muted hover:text-canvas-ink'
        }`}
        onclick={() => (mode = 'name')}
      >
        Name &amp; city
      </button>
      <button
        type="button"
        class={`rounded-lg px-3 py-1.5 transition ${
          mode === 'url'
            ? 'bg-white text-canvas-ink shadow-soft'
            : 'text-canvas-muted hover:text-canvas-ink'
        }`}
        onclick={() => (mode = 'url')}
      >
        Google Maps URL
      </button>
    </div>

    <form class="mt-5 space-y-4" onsubmit={handleSubmit}>
      {#if mode === 'name'}
        <div class="space-y-2">
          <label class="label" for="business-name">Business name</label>
          <input
            id="business-name"
            type="text"
            class="field"
            placeholder="e.g. Brewmorphia"
            autocomplete="organization"
            disabled={!authState.user}
            bind:value={businessName}
          />
        </div>
        <div class="space-y-2">
          <label class="label" for="city">City</label>
          <input
            id="city"
            type="text"
            class="field"
            placeholder="e.g. Calicut"
            autocomplete="address-level2"
            disabled={!authState.user}
            bind:value={city}
          />
        </div>
      {:else}
        <div class="space-y-2">
          <label class="label" for="maps-url">Google Maps URL</label>
          <input
            id="maps-url"
            type="url"
            class="field"
            placeholder="https://maps.app.goo.gl/…"
            disabled={!authState.user}
            bind:value={mapsUrl}
          />
          <p class="text-xs text-canvas-muted">
            Open your listing in Google Maps and paste the share link.
          </p>
        </div>
      {/if}

      {#if errorMessage}
        <p class="rounded-xl bg-action-50 px-3 py-2 text-sm text-action-700">{errorMessage}</p>
      {/if}

      <button type="submit" class="btn-primary w-full" disabled={!canSubmit}>
        {#if submitting}
          Starting your health check…
        {:else}
          Start my free health check
        {/if}
      </button>

      <p class="text-center text-xs text-canvas-muted">
        Takes about 5–10 minutes. We'll show you each step as it runs.
      </p>
    </form>
  </div>
</section>
