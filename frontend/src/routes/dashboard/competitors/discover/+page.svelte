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
    getDiscoveryScan,
    listCompetitors,
    listDiscoveryScans
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
  const isPaid = $derived(tier !== 'free');
  const competitorLimit = $derived(subState?.limits?.competitors ?? 0);
  // Live "how many slots used" badge for the review-cards UI. Reads from
  // ``trackedForAnchor`` (already refreshed on every successful Track),
  // so users see the cap approach instead of getting blindsided by a 402.
  const trackedCount = $derived(trackedForAnchor.length);
  const atCompetitorCap = $derived(
    competitorLimit > 0 && trackedCount >= competitorLimit
  );

  // Anchor business picker + query input ----------------------------------
  let selectedBusinessId = $state(/** @type {number | null} */ (null));
  let queryText = $state('');
  let submitting = $state(false);
  let submitError = $state(/** @type {string | null} */ (null));

  // Once the user has businesses AND prior scans loaded, pick a
  // sensible default anchor. If they have a recent done scan, prefer
  // THAT scan's business so the gateway ("Revisit your earlier list")
  // shows up immediately. Otherwise fall back to the most recently
  // added business. We wait on ``priorScansLoading`` so we don't
  // briefly default to ``businesses[0]`` before scans arrive and then
  // miss the chance to override (the effect short-circuits once
  // ``selectedBusinessId`` is set).
  $effect(() => {
    if (selectedBusinessId != null) return;
    if (businesses.length === 0) return;
    if (priorScansLoading) return;
    const recentScanBizId = priorScans[0]?.business_id;
    const matchesActive = businesses.some(
      (/** @type {any} */ b) => b.id === recentScanBizId
    );
    selectedBusinessId = matchesActive ? recentScanBizId : businesses[0].id;
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

  // Gateway state — when ``scan_id`` is missing and the user has *any*
  // prior done scan, we show the three-option gateway (Revisit /
  // Manual / Force New) instead of dropping straight into a new-scan
  // form. Pressing "Force New Scan" appends ``?new=1`` and suppresses
  // the gateway.
  const forceNew = $derived($page.url.searchParams.get('new') === '1');
  /** @type {any[]} */
  let priorScans = $state([]);
  let priorScansLoading = $state(true);
  /** Most recent done scan, regardless of which business it was
   *  anchored to. The scan's *results* are independent of the anchor —
   *  the user can still track those competitors against any active
   *  business of theirs — so coupling the gateway to anchor-equality
   *  hid the Revisit card whenever the original anchor business had
   *  since been archived. */
  const latestPriorScan = $derived(priorScans[0] ?? null);
  const showGateway = $derived(
    scanId == null && !forceNew && latestPriorScan != null
  );

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

  // Already-tracked competitors for the current anchor. Used to filter
  // revisit cards so a lead the user tracked AFTER the scan ran doesn't
  // resurface in the review-cards UI as a decision they still owe.
  // The server-side filter in ``discovery_scan_job._filter_out_own_roster``
  // runs once at write time and can't know about subsequent tracks, so
  // we re-check on the client every time the anchor or scan changes.
  /** @type {{ maps_url?: string | null, name?: string | null }[]} */
  let trackedForAnchor = $state([]);

  // The dedup + counter must follow whichever business the *Track*
  // action will *write* to — otherwise the "X / Y tracked" pill and
  // the already-tracked filter disagree with reality. ``trackCard``
  // writes to ``anchorBusiness.id`` (the form's current selection),
  // so dedup reads from the same.
  //
  // Earlier this was ``scan?.business_id ?? selectedBusinessId`` —
  // which made sense when the scan was always anchored to a still-
  // active business, but breaks once the original anchor is archived
  // (or the user simply changes the form's dropdown to a different
  // business than the saved scan was originally anchored to). The
  // result was the counter starting at 0 regardless of existing
  // tracked competitors, and never incrementing as new Tracks
  // landed against a different business.
  const dedupBusinessId = $derived(selectedBusinessId ?? null);

  async function refreshTrackedForAnchor() {
    if (dedupBusinessId == null) {
      trackedForAnchor = [];
      return;
    }
    try {
      const rows = await listCompetitors(dedupBusinessId);
      trackedForAnchor = (rows ?? []).map((/** @type {any} */ c) => ({
        maps_url: c.maps_url,
        name: c.name
      }));
    } catch (err) {
      // Non-fatal — leaves dedup empty, user just sees duplicates with
      // 409s if they re-Track. The original error message surfaces in
      // ``cardError`` so the UX still recovers cleanly.
      console.warn('listCompetitors failed', err);
      trackedForAnchor = [];
    }
  }

  $effect(() => {
    void dedupBusinessId; // re-run on anchor change (form OR loaded scan)
    refreshTrackedForAnchor();
  });

  /** @param {any} r */
  function isAlreadyTracked(r) {
    const url = r.maps_url ?? null;
    const name = (r.name ?? '').trim().toLowerCase();
    for (const t of trackedForAnchor) {
      if (url && t.maps_url && t.maps_url === url) return true;
      if (name && (t.name ?? '').trim().toLowerCase() === name) return true;
    }
    return false;
  }

  const results = $derived(
    /** @type {any[]} */ ((scan?.results ?? []).filter(
      (/** @type {any} */ r) => !isAlreadyTracked(r)
    ))
  );

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
        name: result.name || undefined,
        // Forward whatever the discovery scraper extracted. The
        // backend persists these on the Competitor row, which is
        // what the weekly refresh uses to scrape IG follower / post
        // counts (no website_url scrape — kept on the row for the
        // hub's deep-dive link).
        instagram_url: result.instagram_url || undefined,
        website_url: result.website || result.website_url || undefined,
        // Discovery already resolved the exact Places id — pin it so the first
        // refresh reads this precise listing instead of re-searching by name.
        google_place_id: result.place_id || undefined
      });
      cardState = { ...cardState, [key]: 'tracked' };
      showToast(`${result.name || 'Competitor'} added`);
      // Keep the dedup set fresh so revisiting later doesn't surface
      // anything the user just tracked. Cheap one-shot fetch.
      refreshTrackedForAnchor();
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
   * Four visibility pillars for the 2x2 card grid. All four come from
   * what the discovery scrape actually returned for this lead — no
   * more "we'll check on track" placeholders. Instagram and website
   * resolve to ``present`` (✓) when the scraper extracted a URL for
   * them, or ``unknown`` (—) when it didn't find one.
   * @param {any} result
   * @returns {Array<{ key: string, label: string, status: 'strong' | 'present' | 'unknown' | 'thin', detail: string }>}
   */
  function visibilityPillars(result) {
    const rating = result.rating != null ? Number(result.rating) : null;
    const reviews = result.review_count != null ? Number(result.review_count) : null;
    const igUrl = result.instagram_url || null;
    const siteUrl = result.website || result.website_url || null;

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
        status: /** @type {const} */ (igUrl ? 'present' : 'unknown'),
        detail: igUrl ? 'Found' : '—'
      },
      {
        key: 'website',
        label: 'Website',
        status: /** @type {const} */ (siteUrl ? 'present' : 'unknown'),
        detail: siteUrl ? 'Found' : '—'
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
      return;
    }
    try {
      priorScans = await listDiscoveryScans();
    } catch (err) {
      // Non-fatal — the gateway just won't appear; the user gets the
      // scan form. Surface in a debug log for triage rather than the UI.
      console.warn('listDiscoveryScans failed', err);
    } finally {
      priorScansLoading = false;
    }
  });
</script>

<svelte:head><title>Discover competitors · SEO Health</title></svelte:head>

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
  {:else if showGateway}
    <!-- Gateway: prefer revisiting an earlier list over burning a new
         scan. The revisit CTA is the visual primary; Force New Scan is
         deliberately muted so the user only burns a quota slot when
         the existing list really is exhausted. -->
    <div class="space-y-4">
      <!-- Only surface the revisit card when the earlier scan actually
           found someone. A "0 businesses we already found" card reads as
           broken and nudges nothing — when it's empty we drop it and let
           Add-manually / Force-new-scan lead. -->
      {#if latestPriorScan.result_count > 0}
        <a
          href={`/dashboard/competitors/discover?scan_id=${latestPriorScan.id}`}
          class="card group flex flex-col gap-3 border border-healthy-200 bg-gradient-to-br from-healthy-50/70 to-white p-6 transition hover:-translate-y-0.5 hover:shadow-md sm:flex-row sm:items-center sm:justify-between"
          in:fly={{ y: 6, duration: 220, easing: quintOut }}
        >
          <div class="space-y-1">
            <p class="text-xs font-semibold uppercase tracking-wide text-healthy-700">
              Revisit your earlier list
            </p>
            <p class="text-base font-semibold text-canvas-ink">
              {latestPriorScan.result_count}
              {latestPriorScan.result_count === 1 ? 'business' : 'businesses'} we already
              found for you
            </p>
            <p class="text-xs text-canvas-muted">
              From your last scan — pick up where you left off without re-running the
              scraper.
            </p>
          </div>
          <span class="text-2xl text-healthy-600 sm:ml-4">→</span>
        </a>
      {/if}

      <div class="grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          class="card flex flex-col items-start gap-1 p-5 text-left transition hover:border-canvas-ink/10 hover:shadow-sm"
          onclick={openManualAdd}
        >
          <p class="text-xs font-semibold uppercase tracking-wide text-canvas-muted">
            Add manually
          </p>
          <p class="text-sm font-medium text-canvas-ink">
            Paste a Google Maps URL
          </p>
          <p class="text-xs text-canvas-muted">
            Fast path when you already know who to track.
          </p>
        </button>

        <a
          href="/dashboard/competitors/discover?new=1"
          class="card flex flex-col items-start gap-1 border-dashed border-canvas-soft bg-canvas-soft/30 p-5 text-left text-canvas-muted transition hover:bg-canvas-soft/60 hover:text-canvas-ink"
        >
          <p class="text-xs font-semibold uppercase tracking-wide">
            Force new scan
          </p>
          <p class="text-sm font-medium">
            Run the scraper from scratch
          </p>
          <p class="text-xs">
            Uses one of your monthly scan slots. Most of the list will likely
            overlap with what we already found.
          </p>
        </a>
      </div>
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
          <div class="flex flex-wrap items-center justify-between gap-2 text-xs">
            <span class="font-medium text-canvas-ink">
              {position} <span class="text-canvas-muted">/ {total} suggestions</span>
            </span>
            <div class="flex flex-wrap items-center gap-2">
              {#if competitorLimit > 0}
                <span
                  class={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-xs font-medium ${
                    atCompetitorCap
                      ? 'bg-attention-50 text-attention-700'
                      : 'bg-canvas-soft text-canvas-ink/80'
                  }`}
                  title={atCompetitorCap
                    ? 'You’ve reached your plan’s competitor cap. Remove one to track another.'
                    : `${competitorLimit - trackedCount} ${competitorLimit - trackedCount === 1 ? 'slot' : 'slots'} left on your plan`}
                >
                  <span
                    class={`h-1.5 w-1.5 rounded-full ${
                      atCompetitorCap ? 'bg-attention-500' : 'bg-canvas-muted/70'
                    }`}
                  ></span>
                  {trackedCount} / {competitorLimit} tracked
                </span>
              {/if}
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
    class="pointer-events-none fixed inset-x-0 bottom-24 z-40 flex justify-center px-4 sm:bottom-6"
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
