<script>
  import { onDestroy, onMount } from 'svelte';
  import { fly, fade, slide } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { addCompetitor } from '$lib/api.js';

  /**
   * Manual Add Competitor modal.
   *
   * Two distinct input modes — see prompt 03_manual_add:
   *   - "Direct URLs (Fast)": Maps URL + optional IG/website. All three
   *     are persisted on the competitor row so the audit pipeline can
   *     skip the Maps-listing → social-link extraction on first run.
   *   - "Search by Name (Slow)": name + location. We synthesize a Maps
   *     search URL and submit that — the standard competitor audit
   *     pipeline picks it up on the next audit (no Outflow discovery).
   *
   * @type {{
   *   businesses: any[],
   *   defaultBusinessId?: number | null,
   *   onClose: () => void,
   *   onAdded?: () => void
   * }}
   */
  let { businesses, defaultBusinessId = null, onClose, onAdded = () => {} } = $props();

  /** @type {'url' | 'search'} */
  let mode = $state('url');
  let selectedBusinessId = $state(/** @type {number | null} */ (null));

  // Initialise the anchor business once props are wired up — referencing
  // props directly inside `$state(...)` only captures their initial value.
  $effect(() => {
    if (selectedBusinessId == null) {
      selectedBusinessId = defaultBusinessId ?? businesses[0]?.id ?? null;
    }
  });

  // Direct URL inputs
  let mapsUrl = $state('');
  let competitorName = $state('');
  let instagramUrl = $state('');
  let websiteUrl = $state('');

  // Search-by-name inputs
  let searchName = $state('');
  let searchLocation = $state('');

  let submitting = $state(false);
  let submitError = $state(/** @type {string | null} */ (null));
  let submitted = $state(false);

  const anchorBusiness = $derived(
    businesses.find((/** @type {any} */ b) => b.id === selectedBusinessId) ?? null
  );

  // Pre-fill the location for the search mode when an anchor is picked.
  $effect(() => {
    if (anchorBusiness && !searchLocation) {
      searchLocation = anchorBusiness.city ?? '';
    }
  });

  /** @param {string} input */
  function buildMapsSearchUrl(input) {
    return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(input)}`;
  }

  async function handleSubmit() {
    if (submitting) return;
    if (!anchorBusiness) {
      submitError = 'Pick a business to track this competitor under.';
      return;
    }

    submitError = null;
    submitting = true;

    try {
      if (mode === 'url') {
        const url = mapsUrl.trim();
        if (!url) {
          submitError = 'Paste the competitor’s Google Maps URL.';
          submitting = false;
          return;
        }
        await addCompetitor(anchorBusiness.id, {
          maps_url: url,
          name: competitorName.trim() || undefined,
          instagram_url: instagramUrl.trim() || undefined,
          website_url: websiteUrl.trim() || undefined
        });
      } else {
        const name = searchName.trim();
        const location = searchLocation.trim();
        if (!name || !location) {
          submitError = 'Add both a business name and a location to search for.';
          submitting = false;
          return;
        }
        const synth = buildMapsSearchUrl(`${name} ${location}`);
        await addCompetitor(anchorBusiness.id, { maps_url: synth, name });
      }
      submitted = true;
      onAdded();
    } catch (err) {
      submitError = err instanceof Error ? err.message : 'Could not add this competitor.';
    } finally {
      submitting = false;
    }
  }

  /** @param {KeyboardEvent} event */
  function onKey(event) {
    if (event.key === 'Escape') onClose();
  }

  // Mobile swipe-to-dismiss — same pattern as FindingModal so the close
  // affordance isn't just a thumb-stretch ✕ in the top-right. The handle
  // is visible only below sm: because that's the bottom-sheet layout.
  let touchStartY = 0;
  let touchCurrentY = 0;
  let dragging = $state(false);
  let dragOffset = $state(0);
  const DISMISS_THRESHOLD_PX = 80;

  /** @param {TouchEvent} event */
  function onTouchStart(event) {
    touchStartY = event.touches[0].clientY;
    touchCurrentY = touchStartY;
    dragging = true;
  }

  /** @param {TouchEvent} event */
  function onTouchMove(event) {
    if (!dragging) return;
    touchCurrentY = event.touches[0].clientY;
    // Downward drag only — pulling up shouldn't do anything.
    dragOffset = Math.max(0, touchCurrentY - touchStartY);
  }

  function onTouchEnd() {
    if (!dragging) return;
    dragging = false;
    if (dragOffset > DISMISS_THRESHOLD_PX) {
      onClose();
    }
    dragOffset = 0;
  }

  onMount(() => {
    document.addEventListener('keydown', onKey);
    document.body.style.overflow = 'hidden';
  });

  onDestroy(() => {
    document.removeEventListener('keydown', onKey);
    document.body.style.overflow = '';
  });
</script>

<div
  class="fixed inset-0 z-50 flex items-end justify-center bg-canvas-ink/40 px-3 py-6 sm:items-center sm:py-12"
  in:fade={{ duration: 200 }}
  out:fade={{ duration: 150 }}
  onclick={onClose}
  role="presentation"
>
  <div
    class="relative w-full max-w-xl overflow-hidden rounded-3xl bg-white shadow-soft"
    style={dragging
      ? `transform: translateY(${dragOffset}px); transition: none;`
      : 'transform: translateY(0); transition: transform 200ms ease-out;'}
    in:fly={{ y: 16, duration: 320, easing: quintOut }}
    out:fly={{ y: 12, duration: 200 }}
    onclick={(e) => e.stopPropagation()}
    role="dialog"
    aria-modal="true"
    aria-label="Add a competitor manually"
  >
    <!-- Mobile-only drag handle. Touch listeners measure the swipe and
         onClose() fires once the user pulls past DISMISS_THRESHOLD_PX. -->
    <div
      class="absolute inset-x-0 top-0 z-10 flex h-6 cursor-grab touch-none items-center justify-center sm:hidden"
      ontouchstart={onTouchStart}
      ontouchmove={onTouchMove}
      ontouchend={onTouchEnd}
      ontouchcancel={onTouchEnd}
      role="presentation"
    >
      <span class="h-1 w-10 rounded-full bg-canvas-soft" aria-hidden="true"></span>
    </div>

    <button
      type="button"
      onclick={onClose}
      class="absolute right-4 top-4 z-10 grid h-9 w-9 place-items-center rounded-full bg-canvas-soft text-canvas-muted transition hover:bg-canvas-soft/80 hover:text-canvas-ink"
      aria-label="Close"
    >
      ✕
    </button>

    <div class="max-h-[85vh] overflow-y-auto p-6 sm:p-8">
      {#if submitted}
        <!-- Wait & Notify state — analog of the Discovery scan's waiting
             UI. The POST returned, but the actual scrape happens on the
             next audit cycle, so the message frames the wait around that. -->
        <div class="space-y-4" in:fade={{ duration: 220 }}>
          <p class="text-2xl">✅</p>
          <h2 class="text-xl font-semibold tracking-tight text-canvas-ink">
            Got it — we'll take it from here
          </h2>
          <p class="text-sm text-canvas-muted">
            We'll start gathering data on this competitor with the next audit. You'll see them
            on the Competitor Hub once observations are in.
          </p>
          {#if mode === 'search'}
            <p class="text-xs text-canvas-muted">
              Heads up: name-and-location lookups take longer because the scraper has to resolve
              the listing first. If we can't find a match, the entry will sit empty until you
              swap in a direct Google Maps URL.
            </p>
          {/if}
          <div class="flex flex-wrap gap-2">
            <button type="button" class="btn-primary" onclick={onClose}>Done</button>
          </div>
        </div>
      {:else}
        <h2 class="text-xl font-semibold tracking-tight text-canvas-ink">
          Add a competitor manually
        </h2>
        <p class="mt-1 text-sm text-canvas-muted">
          Skip discovery and tell us exactly who to track. We'll fold them into your next audit.
        </p>

        <form
          class="mt-5 space-y-4"
          onsubmit={(e) => {
            e.preventDefault();
            handleSubmit();
          }}
        >
          {#if businesses.length > 1}
            <div class="space-y-1.5">
              <label class="label" for="manual-anchor">Track under</label>
              <select id="manual-anchor" class="field" bind:value={selectedBusinessId}>
                {#each businesses as biz (biz.id)}
                  <option value={biz.id}>{biz.name} · {biz.city}</option>
                {/each}
              </select>
            </div>
          {/if}

          <!-- Mode toggle -->
          <div class="space-y-1.5">
            <span class="label">Input type</span>
            <div class="inline-flex w-full rounded-xl bg-canvas-soft p-1 text-xs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'url'}
                class={`min-h-[36px] flex-1 rounded-lg px-3 py-1.5 transition-all duration-200 ${
                  mode === 'url'
                    ? 'bg-white text-canvas-ink shadow-soft'
                    : 'text-canvas-muted hover:text-canvas-ink'
                }`}
                onclick={() => (mode = 'url')}
              >
                Direct URLs <span class="text-canvas-muted">· Fast</span>
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === 'search'}
                class={`min-h-[36px] flex-1 rounded-lg px-3 py-1.5 transition-all duration-200 ${
                  mode === 'search'
                    ? 'bg-white text-canvas-ink shadow-soft'
                    : 'text-canvas-muted hover:text-canvas-ink'
                }`}
                onclick={() => (mode = 'search')}
              >
                Search by name <span class="text-canvas-muted">· Slow</span>
              </button>
            </div>
          </div>

          <!-- Speed warning. Colour shifts with mode so it's not just
               decorative — slow path gets attention-tint, fast path stays
               quiet (informational). -->
          {#if mode === 'url'}
            <p
              class="rounded-xl border border-healthy-100 bg-healthy-50/70 px-3 py-2 text-xs text-canvas-ink"
            >
              Direct URLs are the fast path — the scraper can pull this listing's metrics on the
              next audit without a search step.
            </p>
          {:else}
            <p
              class="rounded-xl border border-attention-100 bg-attention-50/70 px-3 py-2 text-xs text-canvas-ink"
            >
              Searching by name and location takes longer — the scraper has to resolve the
              listing before it can read any metrics. Direct URLs are significantly faster.
            </p>
          {/if}

          {#if mode === 'url'}
            <div class="space-y-3" transition:slide={{ duration: 200 }}>
              <div class="space-y-1.5">
                <label class="label" for="manual-maps-url">Google Maps URL</label>
                <input
                  id="manual-maps-url"
                  type="url"
                  class="field"
                  placeholder="https://maps.app.goo.gl/…"
                  bind:value={mapsUrl}
                  autocomplete="off"
                />
              </div>
              <div class="space-y-1.5">
                <label class="label" for="manual-name">
                  Display name <span class="text-canvas-muted font-normal">(optional)</span>
                </label>
                <input
                  id="manual-name"
                  type="text"
                  class="field"
                  placeholder="e.g. The Other Café"
                  bind:value={competitorName}
                />
              </div>
              <div class="space-y-1.5">
                <label class="label" for="manual-instagram">
                  Instagram URL <span class="text-canvas-muted font-normal">(optional)</span>
                </label>
                <input
                  id="manual-instagram"
                  type="url"
                  class="field"
                  placeholder="https://instagram.com/…"
                  bind:value={instagramUrl}
                  autocomplete="off"
                />
              </div>
              <div class="space-y-1.5">
                <label class="label" for="manual-website">
                  Website URL <span class="text-canvas-muted font-normal">(optional)</span>
                </label>
                <input
                  id="manual-website"
                  type="url"
                  class="field"
                  placeholder="https://…"
                  bind:value={websiteUrl}
                  autocomplete="off"
                />
              </div>
            </div>
          {:else}
            <div class="space-y-3" transition:slide={{ duration: 200 }}>
              <div class="space-y-1.5">
                <label class="label" for="manual-search-name">Business name</label>
                <input
                  id="manual-search-name"
                  type="text"
                  class="field"
                  placeholder="e.g. The Other Café"
                  bind:value={searchName}
                />
              </div>
              <div class="space-y-1.5">
                <label class="label" for="manual-search-location">Location</label>
                <input
                  id="manual-search-location"
                  type="text"
                  class="field"
                  placeholder="e.g. Fort Kochi"
                  bind:value={searchLocation}
                />
                <p class="text-xs text-canvas-muted">
                  Narrow it down — neighbourhood + city beats just the city.
                </p>
              </div>
            </div>
          {/if}

          {#if submitError}
            <p
              class="rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700"
              transition:slide={{ duration: 180 }}
            >
              {submitError}
            </p>
          {/if}

          <div class="flex justify-end gap-2">
            <button type="button" class="btn-ghost" onclick={onClose}>Cancel</button>
            <button type="submit" class="btn-primary" disabled={submitting}>
              {submitting ? 'Adding…' : 'Track this competitor'}
            </button>
          </div>
        </form>
      {/if}
    </div>
  </div>
</div>
