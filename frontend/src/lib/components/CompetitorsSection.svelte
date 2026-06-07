<script>
  import { onMount } from 'svelte';
  import { fly, fade, slide } from 'svelte/transition';
  import { flip } from 'svelte/animate';
  import { quintOut } from 'svelte/easing';

  import {
    listCompetitors,
    addCompetitor,
    deleteCompetitor,
    getBusinessTrends
  } from '$lib/api.js';
  import { formatRelativeTime } from '$lib/dashboard.js';
  import TrendChart from './TrendChart.svelte';
  import Skeleton from './Skeleton.svelte';

  /**
   * @type {{
   *   businessId: number,
   *   businessName: string,
   *   tier: string,
   *   competitorLimit: number
   * }}
   */
  let { businessId, businessName, tier, competitorLimit } = $props();

  // Both Pro ('paid') and Max qualify — only Free is gated out.
  const isPaid = $derived(tier !== 'free');

  /** @type {any[]} */
  let competitors = $state([]);
  /** @type {{ business: any[], competitors: any[] } | null} */
  let trends = $state(null);
  let loading = $state(true);
  let loadError = $state(/** @type {string | null} */ (null));

  // Add-competitor form state
  let formOpen = $state(false);
  let mapsUrl = $state('');
  let competitorName = $state('');
  let submitting = $state(false);
  let formError = $state(/** @type {string | null} */ (null));

  // Metric toggle — review count by default since most users see growth
  // there before the rating dial moves.
  let metric = $state(/** @type {'review_count' | 'rating'} */ ('review_count'));

  /** @type {Record<number, boolean>} */
  let removingId = $state({});

  // Confirm-to-remove inline UI — replaces the OS-level confirm() dialog,
  // which felt jarring against the rest of the calm UX.
  let confirmingId = $state(/** @type {number | null} */ (null));

  const atLimit = $derived(isPaid && competitors.length >= competitorLimit);

  async function loadAll() {
    loading = true;
    loadError = null;
    try {
      const [c, t] = await Promise.all([
        isPaid ? listCompetitors(businessId) : Promise.resolve([]),
        getBusinessTrends(businessId)
      ]);
      competitors = c;
      trends = t;
    } catch (err) {
      loadError = err instanceof Error ? err.message : 'Could not load competitors.';
    } finally {
      loading = false;
    }
  }

  onMount(loadAll);

  /** @param {SubmitEvent} event */
  async function handleAdd(event) {
    event.preventDefault();
    if (submitting) return;
    const url = mapsUrl.trim();
    if (!url) {
      formError = 'Please paste a Google Maps URL.';
      return;
    }
    submitting = true;
    formError = null;
    try {
      await addCompetitor(businessId, {
        maps_url: url,
        name: competitorName.trim() || undefined
      });
      mapsUrl = '';
      competitorName = '';
      formOpen = false;
      await loadAll();
    } catch (err) {
      // 402: tier limit. 409: duplicate. Both surface as readable messages
      // from the API; just show whatever the backend said.
      formError = err instanceof Error ? err.message : 'Could not add this competitor.';
    } finally {
      submitting = false;
    }
  }

  /** @param {any} competitor */
  function startRemove(competitor) {
    confirmingId = competitor.id;
  }

  function cancelRemove() {
    confirmingId = null;
  }

  /** @param {any} competitor */
  async function confirmRemove(competitor) {
    if (removingId[competitor.id]) return;
    removingId = { ...removingId, [competitor.id]: true };
    try {
      await deleteCompetitor(businessId, competitor.id);
      confirmingId = null;
      await loadAll();
    } catch (err) {
      loadError = err instanceof Error ? err.message : 'Could not remove this competitor.';
    } finally {
      removingId = { ...removingId, [competitor.id]: false };
    }
  }
</script>

<section class="space-y-5">
  <header class="flex flex-wrap items-end justify-between gap-3">
    <div>
      <h2 class="text-lg font-semibold text-canvas-ink">Competitors</h2>
      <p class="text-xs text-canvas-muted">
        See how your rating and review count stack up against nearby businesses over time.
      </p>
    </div>
    {#if isPaid && !loading && !atLimit}
      <button
        type="button"
        class="btn-ghost"
        onclick={() => (formOpen = !formOpen)}
      >
        {formOpen ? 'Cancel' : '+ Add competitor'}
      </button>
    {/if}
  </header>

  {#if loadError}
    <div
      class="card flex flex-wrap items-center justify-between gap-3 border border-action-100 bg-action-50 p-4 text-sm text-action-700"
      in:fade={{ duration: 200 }}
    >
      <div>
        <p class="font-medium">We couldn't load competitor data right now.</p>
        <p class="text-xs text-action-700/80">{loadError}</p>
      </div>
      <button
        type="button"
        class="btn-ghost text-action-700"
        onclick={loadAll}
      >
        ↻ Try again
      </button>
    </div>
  {/if}

  {#if !isPaid}
    <!-- Free-tier upsell. Server enforces the 402 on POST too; this just
         spares free users from filling in a form they can't submit. -->
    <div
      class="card flex flex-col gap-3 border border-attention-100 bg-attention-50/70 px-4 py-3 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between"
    >
      <div class="text-sm text-canvas-ink">
        <p class="font-medium">Track up to 3 competitors</p>
        <p class="text-xs text-canvas-muted">
          Upgrade to compare your rating and review growth against nearby businesses.
        </p>
      </div>
      <a class="btn-primary w-full sm:w-auto" href="/billing">Upgrade to paid</a>
    </div>
  {/if}

  {#if isPaid && formOpen}
    <form
      class="card space-y-3 p-4"
      onsubmit={handleAdd}
      transition:slide={{ duration: 220, easing: quintOut }}
    >
      <div class="space-y-1.5">
        <label class="label" for="competitor-url">Google Maps URL</label>
        <input
          id="competitor-url"
          type="url"
          class="field"
          placeholder="https://maps.app.goo.gl/…"
          bind:value={mapsUrl}
          autocomplete="off"
        />
        <p class="text-xs text-canvas-muted">
          Open the competitor's listing in Google Maps and paste the share link.
        </p>
      </div>
      <div class="space-y-1.5">
        <label class="label" for="competitor-name">
          Name <span class="text-canvas-muted font-normal">(optional)</span>
        </label>
        <input
          id="competitor-name"
          type="text"
          class="field"
          placeholder="e.g. The Other Café"
          bind:value={competitorName}
        />
      </div>
      {#if formError}
        <p class="rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700">{formError}</p>
      {/if}
      <div class="flex justify-end gap-2">
        <button
          type="button"
          class="btn-ghost"
          onclick={() => {
            formOpen = false;
            formError = null;
          }}
        >
          Cancel
        </button>
        <button type="submit" class="btn-primary" disabled={submitting}>
          {submitting ? 'Adding…' : 'Track competitor'}
        </button>
      </div>
    </form>
  {/if}

  {#if loading}
    <div class="space-y-3" aria-busy="true" aria-live="polite">
      <span class="sr-only">Loading competitor data…</span>
      <Skeleton height="h-72 sm:h-80" width="w-full" rounded="2xl" />
      {#if isPaid}
        <Skeleton height="h-16" width="w-full" rounded="2xl" />
        <Skeleton height="h-16" width="w-full" rounded="2xl" />
      {/if}
    </div>
  {:else}
    <!-- Chart — shown for both tiers. For free users the line just shows
         their own trend (the upsell above explains how to add overlays). -->
    <div class="card p-4 sm:p-5">
      <div class="mb-3 flex flex-wrap items-center justify-between gap-2">
        <p class="text-sm font-medium text-canvas-ink">Trend over time</p>
        <div class="inline-flex rounded-xl bg-canvas-soft p-1 text-xs" role="tablist">
          <button
            type="button"
            role="tab"
            aria-selected={metric === 'review_count'}
            class={`min-h-[32px] rounded-lg px-3 py-1.5 transition-all duration-200 ${
              metric === 'review_count'
                ? 'bg-white text-canvas-ink shadow-soft'
                : 'text-canvas-muted hover:text-canvas-ink'
            }`}
            onclick={() => (metric = 'review_count')}
          >
            Reviews
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={metric === 'rating'}
            class={`min-h-[32px] rounded-lg px-3 py-1.5 transition-all duration-200 ${
              metric === 'rating'
                ? 'bg-white text-canvas-ink shadow-soft'
                : 'text-canvas-muted hover:text-canvas-ink'
            }`}
            onclick={() => (metric = 'rating')}
          >
            Rating
          </button>
        </div>
      </div>
      <TrendChart
        business={trends?.business ?? []}
        competitors={trends?.competitors ?? []}
        businessName={businessName}
        {metric}
      />
    </div>

    {#if isPaid}
      {#if competitors.length === 0}
        <div
          class="card p-5 text-center text-sm text-canvas-muted"
          in:fade={{ duration: 220 }}
        >
          <p class="text-2xl">🔭</p>
          <p class="mt-2 font-medium text-canvas-ink">No competitors tracked yet</p>
          <p class="mt-1 text-xs">
            Add up to {competitorLimit} nearby businesses to see them on the chart above.
          </p>
          <button
            type="button"
            class="btn-primary mt-4 inline-flex"
            onclick={() => (formOpen = true)}
          >
            + Add a competitor
          </button>
        </div>
      {:else}
        <ul class="space-y-3">
          {#each competitors as competitor (competitor.id)}
            <li
              class="card flex flex-col gap-3 p-4 sm:flex-row sm:flex-wrap sm:items-center sm:justify-between"
              animate:flip={{ duration: 240 }}
              in:fly={{ y: 6, duration: 220, easing: quintOut }}
              out:fade={{ duration: 160 }}
            >
              <div class="min-w-0 flex-1">
                <p class="truncate text-sm font-medium text-canvas-ink">
                  {competitor.name}
                </p>
                <p class="text-xs text-canvas-muted">
                  {#if competitor.latest_rating != null}
                    {competitor.latest_rating.toFixed(1)} ★
                    {#if competitor.latest_review_count != null}
                      ({competitor.latest_review_count} reviews)
                    {/if}
                    {#if competitor.latest_observed_at}
                      · last seen {formatRelativeTime(competitor.latest_observed_at + 'Z')}
                    {/if}
                  {:else if competitor.observation_count === 0}
                    We'll start gathering data on the next weekly refresh.
                  {:else}
                    Couldn't read this listing on the last refresh.
                  {/if}
                </p>
              </div>

              {#if confirmingId === competitor.id}
                <div
                  class="flex w-full flex-wrap items-center justify-end gap-2 sm:w-auto"
                  in:fade={{ duration: 150 }}
                >
                  <span class="text-xs text-canvas-muted">Stop tracking?</span>
                  <button
                    type="button"
                    class="btn-ghost text-xs"
                    onclick={cancelRemove}
                    disabled={removingId[competitor.id]}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    class="inline-flex min-h-[36px] items-center justify-center rounded-xl bg-action-500 px-3 py-1.5 text-xs font-medium text-white shadow-soft transition hover:bg-action-600 disabled:opacity-60"
                    onclick={() => confirmRemove(competitor)}
                    disabled={removingId[competitor.id]}
                  >
                    {removingId[competitor.id] ? 'Removing…' : 'Yes, remove'}
                  </button>
                </div>
              {:else}
                <button
                  type="button"
                  class="btn-ghost self-start text-xs sm:self-auto"
                  onclick={() => startRemove(competitor)}
                  disabled={removingId[competitor.id]}
                >
                  Remove
                </button>
              {/if}
            </li>
          {/each}
        </ul>
        {#if atLimit}
          <p class="text-xs text-canvas-muted">
            You're at the {competitorLimit}-competitor limit for your plan.
          </p>
        {/if}
      {/if}
    {/if}
  {/if}
</section>
