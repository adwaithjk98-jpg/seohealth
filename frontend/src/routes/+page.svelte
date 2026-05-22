<script>
  import { onMount } from 'svelte';
  import { fade, fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';
  import { goto } from '$app/navigation';
  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';

  let mode = $state(/** @type {'name' | 'url'} */ ('name'));
  let businessName = $state('');
  let city = $state('');
  let mapsUrl = $state('');
  let website = $state('');
  let igHandle = $state('');
  let submitting = $state(false);
  let errorMessage = $state(/** @type {string | null} */ (null));

  // Lifecycle gate:
  //   ready=false   → waiting on auth + an inflight /api/businesses probe
  //   ready=true & authed user with businesses → already redirected to /dashboard
  //   ready=true & no user → show "Sign in to start" CTA (no disabled form)
  //   ready=true & user but no businesses → show the add-business form
  let ready = $state(false);

  // Tier gate — Free: 1 business cap; Paid: 3. The server enforces this
  // (402 from POST /api/businesses), but we also hide the form so the
  // user gets a clear upgrade nudge instead of submitting and bouncing.
  const subState = $derived(authState.user?.subscription_state ?? null);
  const businessLimit = $derived(subState?.limits?.businesses ?? 1);
  const businessCount = $derived(subState?.business_count ?? 0);
  const atBusinessLimit = $derived(
    !!authState.user && businessCount >= businessLimit
  );
  const overBusinessLimit = $derived(
    !!authState.user && businessCount > businessLimit
  );
  const tier = $derived(subState?.tier ?? authState.user?.plan ?? 'free');

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (authState.user) {
      // M2 — a returning user's plain "/" should land on their dashboard,
      // not a fresh "Add your business" form. The dashboard's
      // "+ Add another business" CTA links to "/?add=1" to opt out of
      // this redirect, so a paid user with room for more businesses can
      // actually reach the form.
      const explicitAdd =
        typeof window !== 'undefined' &&
        new URLSearchParams(window.location.search).has('add');
      if (!explicitAdd) {
        try {
          const res = await fetch('/api/businesses', { credentials: 'same-origin' });
          if (res.ok) {
            const list = await res.json();
            if (Array.isArray(list) && list.length > 0) {
              await goto('/dashboard', { replaceState: true });
              return;
            }
          }
        } catch {
          // Network blip — fall through to the form rather than dead-ending.
        }
      }
    }
    ready = true;
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

      const websiteValue = website.trim();
      if (websiteValue) businessPayload.website = websiteValue;
      const igValue = igHandle.trim().replace(/^@+/, '');
      if (igValue) businessPayload.ig_handle = igValue;

      const businessRes = await fetch('/api/businesses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(businessPayload)
      });

      // 409 from the duplicate-business guard (M1) — bounce them onto
      // their existing dashboard instead of clattering on a second copy.
      if (businessRes.status === 409) {
        const body = await businessRes.json().catch(() => null);
        const existingId = body?.detail?.existing_business_id;
        if (existingId) {
          await goto(`/businesses/${existingId}`);
          return;
        }
      }

      // 402 from the tier-limit guard — free user already at 1 business or
      // paid user already at 3. Bounce them to Billing rather than clatter
      // on a form they can't submit.
      if (businessRes.status === 402) {
        await goto('/billing');
        return;
      }

      if (!businessRes.ok) throw new Error(await readError(businessRes));
      const business = await businessRes.json();

      const auditRes = await fetch('/api/audits', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ business_id: business.id })
      });

      // 409 from the in-flight guard (M4/m10) — bounce onto the running audit.
      if (auditRes.status === 409) {
        const body = await auditRes.json().catch(() => null);
        const runningId = body?.detail?.running_audit_id;
        if (runningId) {
          await goto(`/audits/${runningId}`);
          return;
        }
      }

      if (!auditRes.ok) throw new Error(await readError(auditRes));
      const audit = await auditRes.json();
      await goto(`/audits/${audit.audit_id}`);
    } catch (err) {
      if (err instanceof Error && /401/.test(err.message)) {
        await goto('/login');
        return;
      }
      errorMessage =
        err instanceof Error ? err.message : 'Something went wrong starting your audit.';
      submitting = false;
    }
  }

  async function readError(res) {
    try {
      const data = await res.json();
      if (typeof data?.detail === 'string') return data.detail;
      if (typeof data?.detail?.message === 'string') return data.detail.message;
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
    {#if !ready}
      <p class="text-sm text-canvas-muted">Loading…</p>
    {:else if !authState.user}
      <h2 class="text-lg font-semibold text-canvas-ink">Sign in to start</h2>
      <p class="mt-2 text-sm text-canvas-muted">
        We'll send you a one-tap sign-in link by email, then walk you through your first health
        check together. Takes about 30 seconds to set up.
      </p>
      <a href="/login" class="btn-primary mt-5 w-full">Sign in with email</a>
      <p class="mt-3 text-center text-xs text-canvas-muted">
        No password to remember. No card to enter.
      </p>
    {:else if atBusinessLimit}
      <h2 class="text-lg font-semibold text-canvas-ink">
        {tier === 'free' ? 'Upgrade to add another business' : 'Plan limit reached'}
      </h2>
      <p class="mt-2 text-sm text-canvas-muted">
        {#if tier === 'free'}
          You've used your 1 free business slot. Upgrade to the paid plan to track up to 3 businesses with weekly health checks.
        {:else if overBusinessLimit}
          You're tracking {businessCount} businesses but your plan covers {businessLimit}. We'll keep everything visible — archive one to add a new business going forward.
        {:else}
          You've hit the {businessLimit}-business limit on your plan.
        {/if}
      </p>
      <div class="mt-5 flex flex-wrap gap-3">
        <a href="/dashboard" class="btn-ghost">Back to dashboard</a>
        {#if tier === 'free'}
          <a href="/billing" class="btn-primary">See plans</a>
        {/if}
      </div>
    {:else}
      <h2 class="text-lg font-semibold text-canvas-ink">Add your business</h2>
      <p class="mt-1 text-sm text-canvas-muted">
        Tell us how to find you. We'll handle the rest.
      </p>

      <div
        class="mt-5 inline-flex w-full rounded-xl bg-canvas-soft p-1 text-sm sm:w-auto"
        role="tablist"
      >
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'name'}
          class={`flex-1 rounded-lg px-3 py-2 transition-all duration-200 sm:flex-none ${
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
          role="tab"
          aria-selected={mode === 'url'}
          class={`flex-1 rounded-lg px-3 py-2 transition-all duration-200 sm:flex-none ${
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
          <div
            class="space-y-4"
            in:fly={{ y: 4, duration: 220, easing: quintOut }}
          >
            <div class="space-y-2">
              <label class="label" for="business-name">Business name</label>
              <input
                id="business-name"
                type="text"
                class="field"
                placeholder="e.g. Brewmorphia"
                autocomplete="organization"
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
                bind:value={city}
              />
            </div>
          </div>
        {:else}
          <div
            class="space-y-2"
            in:fly={{ y: 4, duration: 220, easing: quintOut }}
          >
            <label class="label" for="maps-url">Google Maps URL</label>
            <input
              id="maps-url"
              type="url"
              class="field"
              placeholder="https://maps.app.goo.gl/…"
              bind:value={mapsUrl}
            />
            <p class="text-xs text-canvas-muted">
              Open your listing in Google Maps and paste the share link.
            </p>
          </div>
        {/if}

        <div class="space-y-2">
          <label class="label" for="website">Website <span class="text-canvas-muted font-normal">(optional)</span></label>
          <input
            id="website"
            type="url"
            class="field"
            placeholder="https://yourbusiness.com"
            autocomplete="url"
            bind:value={website}
          />
          <p class="text-xs text-canvas-muted">
            Leave blank and we'll try to find it from your Maps listing.
          </p>
        </div>

        <div class="space-y-2">
          <label class="label" for="ig-handle">Instagram handle <span class="text-canvas-muted font-normal">(optional)</span></label>
          <input
            id="ig-handle"
            type="text"
            class="field"
            placeholder="@yourbusiness"
            autocapitalize="none"
            autocorrect="off"
            spellcheck="false"
            bind:value={igHandle}
          />
          <p class="text-xs text-canvas-muted">
            Leave blank and we'll try to find it from your website's social links.
          </p>
        </div>

        {#if errorMessage}
          <p
            class="flex items-start gap-2 rounded-xl bg-action-50 px-3 py-2 text-sm text-action-700"
            role="alert"
            in:fade={{ duration: 180 }}
          >
            <span aria-hidden="true">⚠️</span>
            <span>{errorMessage}</span>
          </p>
        {/if}

        <button type="submit" class="btn-primary w-full" disabled={!canSubmit}>
          {#if submitting}
            <span class="inline-flex items-center justify-center gap-2">
              <span
                class="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                aria-hidden="true"
              ></span>
              Starting your health check…
            </span>
          {:else}
            Start my free health check
          {/if}
        </button>

        <p class="text-center text-xs text-canvas-muted">
          Takes about 5–10 minutes. We'll show you each step as it runs.
        </p>
      </form>
    {/if}
  </div>
</section>
