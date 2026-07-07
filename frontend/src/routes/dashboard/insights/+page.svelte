<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fade, fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import { severityLabel, severityTone, formatRelativeTime } from '$lib/dashboard.js';

  /** @type {{
   *   data: {
   *     groups: Array<{
   *       business: any,
   *       auditId: number | null,
   *       openCount: number,
   *       doneCount: number,
   *       recommendations: any[]
   *     }>,
   *     totalOpen: number,
   *     totalDone: number,
   *     error: string | null
   *   }
   * }} */
  let { data } = $props();

  const groups = $derived(data?.groups ?? []);
  const totalOpen = $derived(data?.totalOpen ?? 0);
  const totalDone = $derived(data?.totalDone ?? 0);
  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );

  const severityToneClasses = {
    healthy: 'bg-healthy-50 text-healthy-700',
    attention: 'bg-attention-50 text-attention-700',
    action: 'bg-action-50 text-action-700',
    muted: 'bg-canvas-soft text-canvas-muted'
  };

  /** Build the same per-finding URL the business detail page uses, so
   * tapping a row drops the user on the canonical mark-as-done surface. */
  function findingHref(/** @type {number | null} */ auditId, /** @type {any} */ rec) {
    if (!auditId) return '#';
    return `/audits/${auditId}/dashboard/sections/${rec.section}?finding=${rec.id}`;
  }

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user || data?.error === 'unauthenticated') {
      await goto('/login', { replaceState: true });
    }
  });
</script>

<svelte:head><title>Insights · SEO Health</title></svelte:head>

<section class="space-y-6">
  <a class="btn-ghost -ml-2 text-xs" href="/dashboard">← Back</a>

  <header>
    <h1 class="text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
      {#if totalOpen === 0}
        All caught up
      {:else}
        <span class="text-healthy-700">{totalOpen}</span>
        {totalOpen === 1 ? 'thing' : 'things'} worth a look
      {/if}
    </h1>
    {#if totalDone > 0}
      <p class="mt-1 text-xs text-canvas-muted">{totalDone} done so far</p>
    {/if}
  </header>

  {#if errorMessage}
    <div
      class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700"
      in:fade={{ duration: 220 }}
    >
      <p class="font-medium">We couldn't load your insights right now.</p>
      <p class="mt-1 text-action-700/80">{errorMessage}</p>
      <button
        type="button"
        class="btn-ghost mt-3 inline-flex text-action-700"
        onclick={() => location.reload()}
      >
        ↻ Try again
      </button>
    </div>
  {:else if groups.length === 0}
    <div class="card p-6 text-center" in:fade={{ duration: 240 }}>
      <p class="text-2xl">🌱</p>
      <p class="mt-2 font-medium text-canvas-ink">No insights yet</p>
      <p class="mt-1 text-sm text-canvas-muted">
        Once a business has a completed health check, its to-dos will collect
        here.
      </p>
      <a href="/dashboard" class="btn-ghost mt-3 inline-flex text-xs">
        ← Back home
      </a>
    </div>
  {:else if totalOpen === 0}
    <div class="card border border-healthy-100 bg-healthy-50/60 p-6 text-center" in:fade={{ duration: 320 }}>
      <p class="text-2xl">🎉</p>
      <p class="mt-2 font-medium text-healthy-700">You're all caught up</p>
      <p class="mt-1 text-sm text-canvas-muted">
        No open recommendations across any of your businesses. We'll keep
        quietly checking and surface anything new.
      </p>
    </div>
  {:else}
    <div class="space-y-6">
      {#each groups as group, gi (group.business.id)}
        <section in:fly={{ y: 8, delay: 50 * gi, duration: 280, easing: quintOut }}>
          <div class="flex flex-wrap items-end justify-between gap-2">
            <div class="min-w-0">
              <a
                href={`/businesses/${group.business.id}`}
                class="inline-flex items-center gap-2 text-base font-semibold text-canvas-ink hover:text-healthy-700"
              >
                {group.business.name}
                <span class="text-canvas-muted">→</span>
              </a>
              <p class="text-xs text-canvas-muted">
                {group.business.city}{#if group.business.country}, {group.business.country}{/if}
                {#if group.business.latest_audit_finished_at}
                  · last checked {formatRelativeTime(group.business.latest_audit_finished_at)}
                {/if}
              </p>
            </div>
            {#if group.openCount > 0 || group.doneCount > 0}
              <p class="text-xs text-canvas-muted">
                {group.recommendations.length} open{group.doneCount > 0
                  ? ` · ${group.doneCount} done`
                  : ''}
              </p>
            {/if}
          </div>

          {#if group.recommendations.length === 0}
            <div
              class="mt-3 card border border-healthy-100 bg-healthy-50/40 p-4 text-sm text-healthy-700"
            >
              <p class="font-medium">All caught up here.</p>
              <p class="mt-1 text-xs text-canvas-muted">
                No open recommendations for this business right now.
              </p>
            </div>
          {:else}
            <ol class="mt-3 space-y-3">
              {#each group.recommendations as rec, idx (rec.id)}
                <li>
                  <a
                    href={findingHref(group.auditId, rec)}
                    class="card flex items-start gap-4 p-5 transition hover:border-canvas-muted/30 hover:shadow-soft"
                  >
                    <span
                      class="grid h-9 w-9 shrink-0 place-items-center rounded-full bg-canvas-soft text-sm font-semibold text-canvas-ink"
                      aria-hidden="true"
                    >
                      {idx + 1}
                    </span>
                    <div class="min-w-0 flex-1">
                      <div class="flex flex-wrap items-center gap-2">
                        <span
                          class={`rounded-full px-2 py-0.5 text-xs font-medium ${severityToneClasses[severityTone(rec.severity)]}`}
                        >
                          {severityLabel(rec.severity)}
                        </span>
                        <span class="text-xs text-canvas-muted">
                          {rec.sectionEmoji} {rec.sectionLabel}
                        </span>
                        {#if rec.estimated_time}
                          <span class="text-xs text-canvas-muted">· {rec.estimated_time}</span>
                        {/if}
                      </div>
                      <p class="mt-1 font-medium text-canvas-ink">{rec.title}</p>
                    </div>
                    <span class="self-center text-canvas-muted">→</span>
                  </a>
                </li>
              {/each}
            </ol>
          {/if}
        </section>
      {/each}
    </div>
  {/if}
</section>
