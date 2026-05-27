<script>
  import { fade, fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';
  import { updateBusinessProfile } from '$lib/api.js';

  /**
   * @type {{
   *   business: any,
   *   onUpdated?: (next: any) => void
   * }}
   *
   * Surfaces the three FTUE questions inline whenever the business
   * row is missing them. Hides itself entirely once ``business_type``
   * is set — that's the single source of truth for "has been asked."
   * has_website / has_instagram are also patched here but they're
   * inferable from the website/ig_handle backfill, so this banner
   * doesn't gate on them.
   */
  let { business, onUpdated = () => {} } = $props();

  const BUSINESS_TYPE_OPTIONS = [
    { value: 'cafe', label: 'Café / restaurant', emoji: '☕' },
    { value: 'salon', label: 'Salon / wellness', emoji: '💆' },
    { value: 'retail', label: 'Retail shop', emoji: '🛍️' },
    { value: 'service', label: 'Service business', emoji: '🔧' },
    { value: 'supplier', label: 'Supplier / B2B', emoji: '📦' },
    { value: 'other', label: 'Something else', emoji: '✨' }
  ];

  let open = $state(false);
  let saving = $state(false);
  let saveError = $state(/** @type {string | null} */ (null));

  // Local drafts seeded from current values, so a partial save (the
  // user fills only ``business_type``) doesn't clobber the inferred
  // ``has_website`` / ``has_instagram``.
  let bizType = $state(/** @type {string | null} */ (business?.business_type ?? null));
  let hasWebsite = $state(/** @type {boolean | null} */ (business?.has_website ?? null));
  let hasInstagram = $state(/** @type {boolean | null} */ (business?.has_instagram ?? null));

  $effect(() => {
    // Re-seed when the parent refreshes the business prop.
    bizType = business?.business_type ?? null;
    hasWebsite = business?.has_website ?? null;
    hasInstagram = business?.has_instagram ?? null;
  });

  // Hide once business_type is filled — that's the marker for "we've
  // asked." Other fields can be patched from the per-business edit
  // affordance later.
  const visible = $derived(!business?.business_type);
  const canSave = $derived(
    !saving && bizType !== null && hasWebsite !== null && hasInstagram !== null
  );

  async function handleSave() {
    if (!canSave) return;
    saving = true;
    saveError = null;
    try {
      const updated = await updateBusinessProfile(business.id, {
        business_type: /** @type {any} */ (bizType),
        has_website: hasWebsite,
        has_instagram: hasInstagram
      });
      onUpdated(updated);
      open = false;
    } catch (err) {
      saveError = err instanceof Error ? err.message : "Couldn't save just now.";
    } finally {
      saving = false;
    }
  }
</script>

{#if visible}
  <section
    class="card border border-attention-100 bg-attention-50/70 p-4 sm:p-5"
    in:fade={{ duration: 200 }}
  >
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="min-w-0 flex-1">
        <p class="text-sm font-semibold text-canvas-ink">Help us tailor the audit</p>
        <p class="mt-1 text-xs text-canvas-muted">
          Tell us what kind of business this is and which channels you use — three taps, no
          typing. We'll skip pillars you don't care about and stop suggesting fixes for
          channels you don't have.
        </p>
      </div>
      {#if !open}
        <button
          type="button"
          class="btn-primary text-xs"
          onclick={() => (open = true)}
        >
          Answer
        </button>
      {/if}
    </div>

    {#if open}
      <div class="mt-4 space-y-4" in:fly={{ y: 4, duration: 200, easing: quintOut }}>
        <div class="space-y-2" role="radiogroup" aria-label="Business type">
          <p class="text-xs font-medium uppercase tracking-wide text-canvas-muted">
            What kind of business is this?
          </p>
          <div class="grid grid-cols-2 gap-2">
            {#each BUSINESS_TYPE_OPTIONS as opt}
              {@const selected = bizType === opt.value}
              <button
                type="button"
                role="radio"
                aria-checked={selected}
                onclick={() => (bizType = opt.value)}
                class={`flex items-center gap-2 rounded-xl border bg-white px-3 py-2.5 text-left text-sm font-medium transition ${
                  selected
                    ? 'border-healthy-300 bg-healthy-50 text-healthy-700'
                    : 'border-canvas-soft text-canvas-ink hover:border-canvas-muted/40'
                }`}
              >
                <span aria-hidden="true">{opt.emoji}</span>
                <span class="min-w-0 truncate">{opt.label}</span>
              </button>
            {/each}
          </div>
        </div>

        <div class="space-y-2" role="radiogroup" aria-label="Has website">
          <p class="text-xs font-medium uppercase tracking-wide text-canvas-muted">
            Do you have a website?
          </p>
          <div class="grid grid-cols-2 gap-2">
            {#each [{ v: true, label: 'Yes' }, { v: false, label: 'Not yet' }] as opt}
              {@const selected = hasWebsite === opt.v}
              <button
                type="button"
                role="radio"
                aria-checked={selected}
                onclick={() => (hasWebsite = opt.v)}
                class={`rounded-xl border bg-white px-3 py-2 text-sm font-medium transition ${
                  selected
                    ? 'border-healthy-300 bg-healthy-50 text-healthy-700'
                    : 'border-canvas-soft text-canvas-ink hover:border-canvas-muted/40'
                }`}
              >
                {opt.label}
              </button>
            {/each}
          </div>
        </div>

        <div class="space-y-2" role="radiogroup" aria-label="Has Instagram">
          <p class="text-xs font-medium uppercase tracking-wide text-canvas-muted">
            Are you on Instagram?
          </p>
          <div class="grid grid-cols-2 gap-2">
            {#each [{ v: true, label: 'Yes' }, { v: false, label: 'Not on Instagram' }] as opt}
              {@const selected = hasInstagram === opt.v}
              <button
                type="button"
                role="radio"
                aria-checked={selected}
                onclick={() => (hasInstagram = opt.v)}
                class={`rounded-xl border bg-white px-3 py-2 text-sm font-medium transition ${
                  selected
                    ? 'border-healthy-300 bg-healthy-50 text-healthy-700'
                    : 'border-canvas-soft text-canvas-ink hover:border-canvas-muted/40'
                }`}
              >
                {opt.label}
              </button>
            {/each}
          </div>
        </div>

        {#if saveError}
          <p class="rounded-xl bg-action-50 px-3 py-2 text-xs text-action-700" role="alert">
            {saveError}
          </p>
        {/if}

        <div class="flex items-center justify-end gap-2">
          <button
            type="button"
            class="btn-ghost text-xs"
            onclick={() => (open = false)}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            type="button"
            class="btn-primary text-xs"
            onclick={handleSave}
            disabled={!canSave}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    {/if}
  </section>
{/if}
