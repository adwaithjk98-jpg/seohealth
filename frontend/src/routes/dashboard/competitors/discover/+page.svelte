<script>
  import { onMount, onDestroy } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { fly, fade, slide } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import {
    addCompetitor,
    createDiscoveryScan,
    getDiscoveryScan
  } from '$lib/api.js';
  import ManualAddCompetitorModal from '$lib/components/ManualAddCompetitorModal.svelte';

  /** @type {{ data: { businesses: any[] | null, error: string | null } }} */
  let { data } = $props();

  const businesses = $derived(data?.businesses ?? []);
  const loaderError = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );

  const subState = $derived(authState.user?.subscription_state ?? null);
  const tier = $derived(subState?.tier ?? authState.user?.plan ?? 'free');
  const isPaid = $derived(tier === 'paid');

  // Anchor business picker + query input ----------------------------------
  let selectedBusinessId = $state(/** @type {number | null} */ (null));
  let queryText = $state('');
  let submitting = $state(false);
  let submitError = $state(/** @type {string | null} */ (null));

  // Once the user has businesses loaded, default to the first one and
  // pre-fill a reasonable query.
  $effect(() => {
    if (selectedBusinessId == null && businesses.length > 0) {
      selectedBusinessId = businesses[0].id;
    }
  });

  const anchorBusiness = $derived(
    businesses.find((/** @type {any} */ b) => b.id === selectedBusinessId) ?? null
  );

  $effect(() => {
    if (anchorBusiness && !queryText) {
      queryText = `Similar businesses to ${anchorBusiness.name} in ${anchorBusiness.city}`;
    }
  });

  // Scan polling ----------------------------------------------------------
  const scanIdParam = $derived($page.url.searchParams.get('scan_id'));
  const scanId = $derived(scanIdParam ? Number(scanIdParam) : null);

  /** @type {any | null} */
  let scan = $state(null);
  let scanError = $state(/** @type {string | null} */ (null));
  /** @type {ReturnType<typeof setInterval> | null} */
  let pollTimer = null;

  async function refreshScan() {
    if (scanId == null) return;
    try {
      scan = await getDiscoveryScan(scanId);
      scanError = null;
    } catch (err) {
      scanError = err instanceof Error ? err.message : 'Could not fetch scan status.';
    }
  }

  function stopPolling() {
    if (pollTimer != null) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  // Polling lifecycle: start as soon as we see a scan_id, stop once it
  // terminates (or we navigate away).
  $effect(() => {
    if (scanId == null) {
      stopPolling();
      scan = null;
      return;
    }
    refreshScan();
    stopPolling();
    pollTimer = setInterval(() => {
      if (scan && (scan.status === 'done' || scan.status === 'failed')) {
        stopPolling();
        return;
      }
      refreshScan();
    }, 8000);
  });

  onDestroy(stopPolling);

  // Card decisions --------------------------------------------------------
  /** @type {Record<string, 'pending' | 'tracking' | 'tracked' | 'skipped'>} */
  let cardState = $state({});
  /** @type {Record<string, string>} */
  let cardError = $state({});
  let revisitSkipped = $state(false);

  /** @param {any} result */
  function cardKey(result) {
    return String(result.maps_url || result.name || JSON.stringify(result));
  }

  const results = $derived(/** @type {any[]} */ (scan?.results ?? []));

  // Reset card decisions whenever a brand new result set arrives, so a
  // re-run doesn't carry over stale skipped/tracked flags.
  $effect(() => {
    if (!scan || scan.status !== 'done') return;
    const fresh = /** @type {Record<string, 'pending'>} */ ({});
    for (const r of /** @type {any[]} */ (scan.results ?? [])) {
      fresh[cardKey(r)] = 'pending';
    }
    cardState = fresh;
    cardError = {};
    revisitSkipped = false;
  });

  /** @param {string} city */
  function normalize(city) {
    return city.trim().toLowerCase();
  }

  /** @param {any} result */
  function isInCity(result) {
    const city = anchorBusiness?.city ? normalize(anchorBusiness.city) : '';
    if (!city) return false;
    const address = result.address ? String(result.address).toLowerCase() : '';
    return address.includes(city);
  }

  const inCityResults = $derived(results.filter(isInCity));
  const nearbyResults = $derived(results.filter((/** @type {any} */ r) => !isInCity(r)));

  // 1-by-1 stack order: in-city first (still the right thing to surface),
  // then nearby. No visible grouping; we just preserve that ordering.
  const orderedResults = $derived([...inCityResults, ...nearbyResults]);

  const pendingResults = $derived(
    orderedResults.filter(
      (/** @type {any} */ r) =>
        cardState[cardKey(r)] === 'pending' || cardState[cardKey(r)] === 'tracking'
    )
  );
  const skippedResults = $derived(
    orderedResults.filter((/** @type {any} */ r) => cardState[cardKey(r)] === 'skipped')
  );
  const trackedResults = $derived(
    orderedResults.filter((/** @type {any} */ r) => cardState[cardKey(r)] === 'tracked')
  );

  // The card on screen is always the first un-decided one in order. When
  // there are no more, the completion state takes over.
  const currentResult = $derived(pendingResults[0] ?? null);
  const currentIndex = $derived(
    currentResult ? orderedResults.indexOf(currentResult) : orderedResults.length
  );

  const allReviewed = $derived(
    orderedResults.length > 0 && pendingResults.length === 0 && !revisitSkipped
  );

  // Pick which results to render — when "Revisit Skipped" is clicked we
  // flip just the skipped batch back to pending.
  function handleRevisitSkipped() {
    const next = { ...cardState };
    for (const r of skippedResults) {
      next[cardKey(r)] = 'pending';
    }
    cardState = next;
    cardError = {};
    revisitSkipped = true;
  }

  // Toast on Track success. One-at-a-time — a fresh Track replaces the
  // previous toast so the user always sees the most recent confirmation.
  let toastMessage = $state(/** @type {string | null} */ (null));
  /** @type {ReturnType<typeof setTimeout> | null} */
  let toastTimer = null;

  /** @param {string} message */
  function showToast(message) {
    if (toastTimer) clearTimeout(toastTimer);
    toastMessage = message;
    // ~4s read window. Long enough to register the confirmation without
    // hanging around past the user's next decision.
    toastTimer = setTimeout(() => {
      toastMessage = null;
      toastTimer = null;
    }, 4000);
  }

  onDestroy(() => {
    if (toastTimer) clearTimeout(toastTimer);
  });

  /** @param {any} result */
  async function trackCard(result) {
    const key = cardKey(result);
    if (cardState[key] !== 'pending') return;
    if (!anchorBusiness) return;
    cardState = { ...cardState, [key]: 'tracking' };
    cardError = { ...cardError, [key]: '' };
    try {
      await addCompetitor(anchorBusiness.id, {
        maps_url: result.maps_url || '',
        name: result.name || undefined
      });
      cardState = { ...cardState, [key]: 'tracked' };
      showToast(`${result.name || 'Competitor'} added`);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Could not track this competitor.';
      // 402 (paid-tier limit hit) and 409 (already tracking) are the common
      // cases — surface backend copy so the user sees what's going on.
      cardError = { ...cardError, [key]: message };
      cardState = { ...cardState, [key]: 'pending' };
    }
  }

  /** @param {any} result */
  function skipCard(result) {
    const key = cardKey(result);
    if (cardState[key] !== 'pending') return;
    cardState = { ...cardState, [key]: 'skipped' };
  }

  // Form submission ------------------------------------------------------
  async function handleSubmit() {
    if (submitting) return;
    if (!anchorBusiness) {
      submitError = 'Pick a business to anchor this scan to.';
      return;
    }
    const query = queryText.trim();
    if (!query) {
      submitError = 'What kind of businesses should we look for?';
      return;
    }
    submitting = true;
    submitError = null;
    try {
      const created = await createDiscoveryScan({
        business_id: anchorBusiness.id,
        query
      });
      const params = new URLSearchParams($page.url.searchParams);
      params.set('scan_id', String(created.id));
      await goto(`?${params.toString()}`, { keepFocus: true, replaceState: false });
    } catch (err) {
      submitError = err instanceof Error ? err.message : 'Could not start the scan.';
    } finally {
      submitting = false;
    }
  }

  let manualAddOpen = $state(false);

  function openManualAdd() {
    manualAddOpen = true;
  }

  function closeManualAdd() {
    manualAddOpen = false;
  }

  // --- Card presentation helpers ----------------------------------------
  // Per prompt 09: compensate for the no-images rule with stronger typography
  // (category emoji, why-similar checklist, 2x2 visibility snapshot). All
  // of this is *derived from the scrape data* — we don't invent metrics.

  /** @param {string | null | undefined} category */
  function categoryEmoji(category) {
    if (!category) return '🏢';
    const lower = category.toLowerCase();
    if (lower.includes('cafe') || lower.includes('coffee')) return '☕️';
    if (lower.includes('bakery') || lower.includes('pâtisserie')) return '🥐';
    if (lower.includes('restaurant') || lower.includes('eatery') || lower.includes('food'))
      return '🍽️';
    if (lower.includes('bar') || lower.includes('pub') || lower.includes('brew')) return '🍻';
    if (lower.includes('clinic') || lower.includes('hospital') || lower.includes('medical'))
      return '🏥';
    if (lower.includes('dental') || lower.includes('dentist')) return '🦷';
    if (lower.includes('salon') || lower.includes('barber') || lower.includes('beauty'))
      return '💇';
    if (lower.includes('spa') || lower.includes('massage') || lower.includes('wellness'))
      return '🧖';
    if (lower.includes('gym') || lower.includes('fitness') || lower.includes('yoga'))
      return '💪';
    if (lower.includes('hotel') || lower.includes('resort') || lower.includes('stay'))
      return '🏨';
    if (lower.includes('school') || lower.includes('academy') || lower.includes('tuition'))
      return '🏫';
    if (lower.includes('store') || lower.includes('shop') || lower.includes('boutique'))
      return '🛍️';
    if (lower.includes('garage') || lower.includes('auto') || lower.includes('mechanic'))
      return '🔧';
    return '🏢';
  }

  /**
   * Why we think a discovery result is similar — derived only from the
   * fields the scrape returned. Each entry is a short, honest reason the
   * card UI renders as a checklist item.
   * @param {any} result
   */
  function whyItsSimilar(result) {
    /** @type {string[]} */
    const reasons = [];
    if (anchorBusiness?.city && result.address) {
      const city = anchorBusiness.city.toLowerCase();
      if (String(result.address).toLowerCase().includes(city)) {
        reasons.push(`Same neighborhood as ${anchorBusiness.city}`);
      } else {
        reasons.push(`In your wider area`);
      }
    }
    if (result.category) {
      reasons.push(`Category: ${result.category}`);
    }
    if (result.rating != null) {
      const rating = Number(result.rating);
      if (rating >= 4.3) {
        reasons.push(`Well-rated locally (${rating.toFixed(1)}★)`);
      } else if (rating >= 3.8) {
        reasons.push(`Solid customer reputation (${rating.toFixed(1)}★)`);
      } else {
        reasons.push(`Active listing (${rating.toFixed(1)}★)`);
      }
    }
    if (result.review_count != null && Number(result.review_count) > 0) {
      const n = Number(result.review_count);
      if (n >= 200) reasons.push(`High volume of reviews (${n})`);
      else if (n >= 50) reasons.push(`Moderate review activity (${n})`);
      else reasons.push(`Early review signal (${n})`);
    }
    return reasons;
  }

  /**
   * Four visibility pillars for the 2x2 card grid. The scrape currently
   * pulls Maps + Reviews; Instagram/Website aren't in the default field
   * set so they show as ``unknown`` (muted dot, "we'll check on track"
   * copy). Switching to a "real" reading requires expanding the fields
   * payload in createDiscoveryScan.
   * @param {any} result
   * @returns {Array<{ key: string, label: string, status: 'strong' | 'present' | 'unknown' | 'thin', detail: string }>}
   */
  function visibilityPillars(result) {
    const rating = result.rating != null ? Number(result.rating) : null;
    const reviews = result.review_count != null ? Number(result.review_count) : null;

    /** @type {'strong' | 'present' | 'unknown' | 'thin'} */
    let mapsStatus = 'unknown';
    let mapsDetail = '—';
    if (rating != null) {
      mapsDetail = `${rating.toFixed(1)} ★`;
      mapsStatus = rating >= 4.3 ? 'strong' : rating >= 3.8 ? 'present' : 'thin';
    }

    /** @type {'strong' | 'present' | 'unknown' | 'thin'} */
    let reviewsStatus = 'unknown';
    let reviewsDetail = '—';
    if (reviews != null) {
      reviewsDetail = `${reviews} total`;
      reviewsStatus = reviews >= 200 ? 'strong' : reviews >= 50 ? 'present' : 'thin';
    }

    return [
      { key: 'maps', label: 'Maps', status: mapsStatus, detail: mapsDetail },
      { key: 'reviews', label: 'Reviews', status: reviewsStatus, detail: reviewsDetail },
      {
        key: 'instagram',
        label: 'Instagram',
        status: /** @type {const} */ ('unknown'),
        detail: 'Checked on track'
      },
      {
        key: 'website',
        label: 'Website',
        status: /** @type {const} */ ('unknown'),
        detail: 'Checked on track'
      }
    ];
  }

  /** @param {'strong' | 'present' | 'unknown' | 'thin'} status */
  function pillarDotClass(status) {
    if (status === 'strong') return 'bg-healthy-500';
    if (status === 'present') return 'bg-healthy-300';
    if (status === 'thin') return 'bg-attention-400';
    return 'bg-canvas-soft border border-canvas-muted/30';
  }

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user || data?.error === 'unauthenticated') {
      await goto('/login', { replaceState: true });
    }
  });
</script>

<section class="space-y-6">
  <header class="flex items-center justify-between gap-3">
    <div>
      <a class="btn-ghost -ml-2 text-xs" href="/dashboard/competitors">← Back to hub</a>
      <h1 class="mt-2 text-2xl font-semibold tracking-tight text-canvas-ink sm:text-3xl">
        Find similar businesses
      </h1>
    </div>
  </header>

  {#if loaderError}
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">We couldn't load your businesses.</p>
      <p class="mt-1 text-action-700/80">{loaderError}</p>
    </div>
  {:else if !isPaid}
    <div
      class="card flex flex-col gap-3 border border-attention-100 bg-attention-50/70 px-4 py-4 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="text-sm text-canvas-ink">
        <p class="font-medium">Discovery is a paid feature</p>
        <p class="text-xs text-canvas-muted">
          Upgrade to scan your area for similar businesses.
        </p>
      </div>
      <a class="btn-primary w-full sm:w-auto" href="/billing">Upgrade to paid</a>
    </div>
  {:else if businesses.length === 0}
    <div class="card flex flex-col items-start gap-4 p-6 sm:p-8">
      <p class="text-2xl">🏢</p>
      <h2 class="text-lg font-semibold text-canvas-ink">Add a business first</h2>
      <p class="text-sm text-canvas-muted">
        Discovery is anchored to a business you own — that's how we know which area to scan.
      </p>
      <a class="btn-primary w-full sm:w-auto" href="/">Add a business</a>
    </div>
  {:else if scanId == null}
    <!-- Form: pick anchor + query, then kick off the async scan. -->
    <form
      class="card space-y-4 p-5 sm:p-6"
      onsubmit={(e) => {
        e.preventDefault();
        handleSubmit();
      }}
    >
      {#if businesses.length > 1}
        <div class="space-y-1.5">
          <label class="label" for="anchor-business">Anchor business</label>
          <select
            id="anchor-business"
            class="field"
            bind:value={selectedBusinessId}
          >
            {#each businesses as biz (biz.id)}
              <option value={biz.id}>{biz.name} · {biz.city}</option>
            {/each}
          </select>
          <p class="text-xs text-canvas-muted">
            We'll group results by whether they're in {anchorBusiness?.city ?? 'this city'}.
          </p>
        </div>
      {:else if anchorBusiness}
        <p class="text-xs text-canvas-muted">
          Scanning the market around
          <span class="font-medium text-canvas-ink">
            {anchorBusiness.name} · {anchorBusiness.city}
          </span>.
        </p>
      {/if}

      <div class="space-y-1.5">
        <label class="label" for="discovery-query">What to look for</label>
        <input
          id="discovery-query"
          type="text"
          class="field"
          bind:value={queryText}
          placeholder="e.g. cafes in Mumbai"
        />
        <p class="text-xs text-canvas-muted">
          Be specific — Google Maps queries like
          <code class="rounded bg-canvas-soft px-1 py-0.5 text-[11px]">specialty coffee in Kochi</code>
          give the cleanest results.
        </p>
      </div>

      {#if submitError}
        <p class="rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700">
          {submitError}
        </p>
      {/if}

      <div class="flex justify-end gap-2">
        <a class="btn-ghost" href="/dashboard/competitors">Cancel</a>
        <button type="submit" class="btn-primary" disabled={submitting}>
          {submitting ? 'Starting scan…' : 'Start scan'}
        </button>
      </div>
    </form>
  {:else if scanError && !scan}
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">We couldn't load that scan.</p>
      <p class="mt-1 text-action-700/80">{scanError}</p>
      <button type="button" class="btn-ghost mt-3 text-action-700" onclick={refreshScan}>
        ↻ Try again
      </button>
    </div>
  {:else if !scan}
    <!-- Initial fetch in flight. -->
    <div class="card flex items-center gap-3 p-6 text-sm text-canvas-muted">
      <span
        class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-healthy-500"
      ></span>
      Loading scan…
    </div>
  {:else if scan.status === 'failed'}
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">This scan didn't complete.</p>
      <p class="mt-1 text-action-700/80">
        {scan.error_message || 'The scraper hit an error mid-run.'}
      </p>
      <div class="mt-3 flex gap-2">
        <a class="btn-primary" href="/dashboard/competitors/discover">Try another scan</a>
        <a class="btn-ghost" href="/dashboard/competitors">Back to hub</a>
      </div>
    </div>
  {:else if scan.status === 'pending' || scan.status === 'running'}
    <div
      class="card flex flex-col items-start gap-4 p-6 sm:p-8"
      in:fade={{ duration: 220 }}
    >
      <div
        class="grid h-12 w-12 place-items-center rounded-2xl bg-healthy-50 text-healthy-700"
        aria-hidden="true"
      >
        <span class="inline-block h-2 w-2 animate-pulse rounded-full bg-healthy-500"></span>
      </div>
      <div class="space-y-2">
        <h2 class="text-lg font-semibold text-canvas-ink">We're scanning your market…</h2>
        <p class="text-sm text-canvas-muted">
          This usually takes around 20 minutes. You can leave this page open or come back later —
          we'll have the suggestions ready when you do.
        </p>
        <p class="text-xs text-canvas-muted">
          Scan #{scan.id} · {scan.status}
        </p>
      </div>
      <a class="btn-ghost" href="/dashboard/competitors">Back to hub</a>
    </div>
  {:else if scan.status === 'done'}
    {#if allReviewed}
      <div
        class="card flex flex-col items-start gap-4 p-6 sm:p-8"
        in:fly={{ y: 6, duration: 240, easing: quintOut }}
      >
        <p class="text-2xl">✅</p>
        <h2 class="text-lg font-semibold text-canvas-ink">You've reviewed all suggestions.</h2>
        <p class="text-sm text-canvas-muted">
          {Object.values(cardState).filter((s) => s === 'tracked').length} tracked ·
          {skippedResults.length} skipped.
        </p>
        <div class="flex flex-wrap gap-2">
          {#if skippedResults.length > 0}
            <button type="button" class="btn-primary" onclick={handleRevisitSkipped}>
              Revisit skipped ({skippedResults.length})
            </button>
          {/if}
          <button type="button" class="btn-ghost" onclick={openManualAdd}>
            + Add manually
          </button>
          <a class="btn-ghost" href="/dashboard/competitors">Back to hub</a>
        </div>
      </div>
    {:else if results.length === 0}
      <div class="card flex flex-col items-start gap-3 p-6 text-sm text-canvas-muted">
        <p class="text-2xl">🔭</p>
        <p class="font-medium text-canvas-ink">No results for that query.</p>
        <p>Try a more specific search like "specialty coffee in Kochi".</p>
        <a class="btn-primary mt-2" href="/dashboard/competitors/discover">Try another scan</a>
      </div>
    {:else}
      <!-- Two grouped sections. Each card decision animates the card out of
           its group; once both groups empty we flip to the completion state. -->
      {#snippet cardItem(/** @type {any} */ result)}
        {@const key = cardKey(result)}
        {@const state = cardState[key] ?? 'pending'}
        {@const reasons = whyItsSimilar(result)}
        {@const pillars = visibilityPillars(result)}
        {#if state === 'pending' || state === 'tracking'}
          <article
            class="card overflow-hidden p-0 shadow-md"
            in:fly={{ y: 12, duration: 260, easing: quintOut }}
            out:fly={{ y: -20, duration: 220, easing: quintOut }}
          >
            <!-- Card hero — typography compensates for the no-image rule. -->
            <div class="flex items-start gap-3 p-5 sm:p-6">
              <div
                class="grid h-12 w-12 shrink-0 place-items-center rounded-2xl bg-healthy-50 text-2xl"
                aria-hidden="true"
              >
                {categoryEmoji(result.category)}
              </div>
              <div class="min-w-0 flex-1">
                <h3 class="text-lg font-semibold tracking-tight text-canvas-ink sm:text-xl">
                  {result.name || 'Unnamed business'}
                </h3>
                <div class="mt-1 flex flex-wrap items-center gap-1.5">
                  {#if result.category}
                    <span
                      class="inline-flex items-center rounded-full bg-canvas-soft px-2 py-0.5 text-xs font-medium text-canvas-ink/80"
                    >
                      {result.category}
                    </span>
                  {/if}
                  {#if result.rating != null}
                    <span
                      class="inline-flex items-center gap-1 rounded-full bg-healthy-50 px-2 py-0.5 text-xs font-medium text-healthy-700"
                    >
                      {Number(result.rating).toFixed(1)} ★
                    </span>
                  {/if}
                </div>
                {#if result.address}
                  <p class="mt-2 text-xs leading-relaxed text-canvas-muted">{result.address}</p>
                {/if}
              </div>
            </div>

            {#if reasons.length > 0}
              <div class="border-t border-canvas-soft px-5 pb-1 pt-4 sm:px-6">
                <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
                  Why it's similar
                </p>
                <ul class="mt-2 space-y-1.5">
                  {#each reasons as reason}
                    <li class="flex items-start gap-2 text-sm text-canvas-ink/90">
                      <span
                        class="mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full bg-healthy-100 text-[10px] text-healthy-700"
                        aria-hidden="true">✓</span
                      >
                      <span class="leading-snug">{reason}</span>
                    </li>
                  {/each}
                </ul>
              </div>
            {/if}

            <div class="px-5 pb-1 pt-4 sm:px-6">
              <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
                Visibility snapshot
              </p>
              <dl class="mt-2 grid grid-cols-2 gap-2">
                {#each pillars as pillar (pillar.key)}
                  <div
                    class={`rounded-xl border p-3 ${
                      pillar.status === 'unknown'
                        ? 'border-canvas-soft bg-canvas-soft/30'
                        : 'border-canvas-soft bg-white'
                    }`}
                  >
                    <div class="flex items-center justify-between gap-2">
                      <dt class="text-xs font-medium text-canvas-ink">{pillar.label}</dt>
                      <span
                        class={`h-2 w-2 rounded-full ${pillarDotClass(pillar.status)}`}
                        aria-hidden="true"
                      ></span>
                    </div>
                    <dd class="mt-1 text-xs text-canvas-muted">{pillar.detail}</dd>
                  </div>
                {/each}
              </dl>
            </div>

            {#if cardError[key]}
              <p
                class="mx-5 mt-4 rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700 sm:mx-6"
                transition:slide={{ duration: 180 }}
              >
                {cardError[key]}
              </p>
            {/if}

            <!-- Anchored actions — full-width on mobile, side-by-side on sm+. -->
            <div
              class="mt-4 flex gap-2 border-t border-canvas-soft bg-canvas-soft/30 p-4 sm:p-5"
            >
              <button
                type="button"
                class="btn-ghost flex-1"
                onclick={() => skipCard(result)}
                disabled={state === 'tracking'}
              >
                Skip
              </button>
              <button
                type="button"
                class="btn-primary flex-1"
                onclick={() => trackCard(result)}
                disabled={state === 'tracking' || !result.maps_url}
                title={!result.maps_url ? 'This result is missing a Google Maps link' : ''}
              >
                {state === 'tracking' ? 'Tracking…' : 'Track'}
              </button>
            </div>
          </article>
        {/if}
      {/snippet}

      <!-- Progress bar + position counter. Total = ordered list length; -->
      <!-- position = how far through we are (1-indexed). -->
      {#if currentResult}
        {@const total = orderedResults.length}
        {@const position = currentIndex + 1}
        {@const isInCity = inCityResults.includes(currentResult)}
        <div class="space-y-3">
          <div class="flex items-center justify-between gap-3 text-xs">
            <span class="font-medium text-canvas-ink">
              {position} <span class="text-canvas-muted">/ {total} suggestions</span>
            </span>
            <span
              class={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
                isInCity
                  ? 'bg-healthy-50 text-healthy-700'
                  : 'bg-canvas-soft text-canvas-ink/80'
              }`}
            >
              <span
                class={`h-1.5 w-1.5 rounded-full ${
                  isInCity ? 'bg-healthy-500' : 'bg-canvas-muted/70'
                }`}
              ></span>
              {isInCity
                ? `Found in ${anchorBusiness?.city ?? 'your city'}`
                : 'Found nearby'}
            </span>
          </div>
          <div
            class="h-1.5 w-full overflow-hidden rounded-full bg-canvas-soft"
            role="progressbar"
            aria-valuemin="0"
            aria-valuemax={total}
            aria-valuenow={position}
          >
            <div
              class="h-full rounded-full bg-healthy-500 transition-[width] duration-300 ease-out"
              style={`width: ${(position / total) * 100}%`}
            ></div>
          </div>
        </div>

        <!-- 1-by-1 card stack. {#key} forces a fresh mount on each new -->
        <!-- currentResult so in/out transitions fire predictably. -->
        {#key cardKey(currentResult)}
          {@render cardItem(currentResult)}
        {/key}
      {/if}
    {/if}
  {/if}
</section>

<!-- Toast — fixed at the bottom, fades + slides in/out. -->
{#if toastMessage}
  <div
    class="pointer-events-none fixed inset-x-0 bottom-6 z-40 flex justify-center px-4"
    in:fly={{ y: 16, duration: 240, easing: quintOut }}
    out:fade={{ duration: 180 }}
    role="status"
    aria-live="polite"
  >
    <div
      class="pointer-events-auto inline-flex items-center gap-3 rounded-full bg-canvas-ink/95 px-4 py-2.5 text-sm font-medium text-white shadow-soft"
    >
      <span class="grid h-5 w-5 place-items-center rounded-full bg-healthy-500 text-[10px]"
        aria-hidden="true">✓</span
      >
      {toastMessage}
    </div>
  </div>
{/if}

{#if manualAddOpen && businesses.length > 0}
  <ManualAddCompetitorModal
    {businesses}
    defaultBusinessId={anchorBusiness?.id ?? null}
    onClose={closeManualAdd}
  />
{/if}
