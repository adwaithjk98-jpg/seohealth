<script>
  import { onMount } from 'svelte';
  import { fly } from 'svelte/transition';
  import { reduced } from '$lib/motion.js';

  /**
   * "An audit just ran" announcement banner. The point is to make it
   * unmistakable that a fresh check landed — especially for *scheduled*
   * audits the user never watched happen — and to pull them toward the
   * insight that explains what moved.
   *
   * Shows once per audit: we remember the last audit id the user has
   * acknowledged (per business) in localStorage, so a returning user sees
   * the banner exactly when there's a newer audit than they last saw, and
   * never again for that same audit once dismissed or clicked through.
   *
   * @type {{
   *   auditId: number,
   *   businessId: number | string,
   *   finishedAt: string | null,
   *   newCount?: number,
   *   href: string
   * }}
   */
  let { auditId, businessId, finishedAt, newCount = 0, href } = $props();

  let show = $state(false);
  const storageKey = $derived(`seenAuditBanner:${businessId}`);

  onMount(() => {
    if (auditId == null) return;
    try {
      const seen = localStorage.getItem(`seenAuditBanner:${businessId}`);
      if (seen !== String(auditId)) show = true;
    } catch {
      // Private mode / storage blocked — still announce once this session.
      show = true;
    }
  });

  function markSeen() {
    try {
      localStorage.setItem(storageKey, String(auditId));
    } catch {
      /* non-fatal */
    }
    show = false;
  }

  /** @param {string | null} iso */
  function fmtDate(iso) {
    if (!iso) return '';
    try {
      return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    } catch {
      return '';
    }
  }
</script>

{#if show}
  <div
    class="card flex items-center justify-between gap-3 border border-healthy-200 bg-gradient-to-br from-healthy-50 to-white p-4"
    role="status"
    in:fly={reduced({ y: -8, duration: 260 })}
  >
    <div class="flex min-w-0 items-start gap-3">
      <span class="text-lg leading-none" aria-hidden="true">✨</span>
      <div class="min-w-0">
        <p class="text-sm font-semibold text-canvas-ink">
          <!-- &nbsp; because the {#if} block's leading whitespace collapses,
               which rendered as "Fresh audit's in— checked". -->
          Fresh audit's in{#if finishedAt}&nbsp;— checked {fmtDate(finishedAt)}{/if}
        </p>
        <p class="text-xs text-canvas-muted">
          {#if newCount > 0}
            {newCount} new thing{newCount === 1 ? '' : 's'} to look at since last time.
          {:else}
            Your latest check is ready — see what moved.
          {/if}
        </p>
      </div>
    </div>
    <div class="flex shrink-0 items-center gap-1.5">
      <a {href} class="btn-primary whitespace-nowrap text-xs" onclick={markSeen}>
        Check insights →
      </a>
      <button
        type="button"
        class="btn-ghost px-2 text-canvas-muted"
        aria-label="Dismiss"
        onclick={markSeen}
      >
        ×
      </button>
    </div>
  </div>
{/if}
