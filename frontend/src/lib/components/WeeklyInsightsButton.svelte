<script>
  import { goto } from '$app/navigation';

  /**
   * The one standalone "Weekly Insights" entry on the home overview. Navigates
   * to the full-screen scroll report. Glows (a pulsing dot) when ANY business
   * has a fresh report the user hasn't opened — computed from the already-
   * loaded business list (`latest_audit_id`), so no extra fetch. Quiet
   * otherwise, to stay on the calm side of the brand.
   *
   * @type {{ businesses?: any[] }}
   */
  let { businesses = [] } = $props();

  let fresh = $state(false);

  const withReport = $derived((businesses ?? []).filter((b) => b?.latest_audit_id != null));
  const hasAny = $derived(withReport.length > 0);

  // localStorage is browser-only; $effect never runs during prerender.
  $effect(() => {
    try {
      fresh = withReport.some(
        (b) => localStorage.getItem(`seenInsights:${b.id}`) !== String(b.latest_audit_id)
      );
    } catch {
      fresh = true;
    }
  });

  function open() {
    try {
      for (const b of withReport) {
        localStorage.setItem(`seenInsights:${b.id}`, String(b.latest_audit_id));
      }
    } catch {
      /* non-fatal */
    }
    goto('/weekly-insights');
  }
</script>

{#if hasAny}
  <button
    type="button"
    onclick={open}
    class="group relative inline-flex items-center gap-2 rounded-full border border-healthy-200 bg-gradient-to-br from-healthy-50 to-white px-4 py-2 text-sm font-medium text-healthy-800 shadow-soft transition hover:-translate-y-0.5 hover:shadow-md"
  >
    <span aria-hidden="true">✨</span>
    Weekly Insights
    <span aria-hidden="true" class="transition group-hover:translate-x-0.5">→</span>
    {#if fresh}
      <span class="absolute -right-1 -top-1 flex h-3 w-3" aria-label="New insights available">
        <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-healthy-400 opacity-75"></span>
        <span class="relative inline-flex h-3 w-3 rounded-full bg-healthy-500"></span>
      </span>
    {/if}
  </button>
{/if}
