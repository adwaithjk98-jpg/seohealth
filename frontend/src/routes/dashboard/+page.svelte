<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fly } from 'svelte/transition';
  import { quintOut } from 'svelte/easing';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import { trendArrow, trendTone, scoreTone, formatRelativeTime } from '$lib/dashboard.js';

  /** @type {{ data: { businesses: any[] | null, error: string | null } }} */
  let { data } = $props();

  const businesses = $derived(data?.businesses ?? []);
  const errorMessage = $derived(
    data?.error && data.error !== 'unauthenticated' ? data.error : null
  );

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user || data?.error === 'unauthenticated') {
      await goto('/login', { replaceState: true });
    }
  });

  const trendToneClass = {
    healthy: 'bg-healthy-50 text-healthy-700',
    attention: 'bg-attention-50 text-attention-700',
    action: 'bg-action-50 text-action-700',
    muted: 'bg-canvas-soft text-canvas-muted'
  };

  const gradeToneClass = {
    healthy: 'bg-healthy-50 text-healthy-700',
    attention: 'bg-attention-50 text-attention-700',
    action: 'bg-action-50 text-action-700',
    muted: 'bg-canvas-soft text-canvas-muted'
  };
</script>

<section class="space-y-8">
  <header>
    <p
      class="inline-flex items-center gap-2 rounded-full border border-healthy-100 bg-healthy-50 px-3 py-1 text-xs font-medium text-healthy-700"
    >
      <span class="h-1.5 w-1.5 rounded-full bg-healthy-500"></span>
      Your businesses
    </p>
    <h1 class="mt-3 text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
      Welcome back{#if authState.user}, <span class="text-healthy-600">{authState.user.email}</span>{/if}
    </h1>
    <p class="mt-2 text-sm text-canvas-muted">
      Pick a business to see its latest health check, or add a new one.
    </p>
  </header>

  {#if errorMessage}
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">{errorMessage}</p>
    </div>
  {:else if businesses.length === 0}
    <div class="card flex flex-col items-start gap-4 p-6 sm:p-8">
      <p class="text-2xl">👋</p>
      <h2 class="text-lg font-semibold text-canvas-ink">No businesses yet</h2>
      <p class="text-sm text-canvas-muted">
        Add your first business and we'll run a free health check right away.
      </p>
      <a class="btn-primary" href="/">Add a business</a>
    </div>
  {:else}
    <div class="grid gap-4 sm:grid-cols-2">
      {#each businesses as biz, i (biz.id)}
        {@const tone = scoreTone(biz.latest_score)}
        {@const arrow = trendArrow(biz.latest_trend)}
        <a
          href={biz.running_audit_id
            ? `/audits/${biz.running_audit_id}`
            : `/businesses/${biz.id}`}
          class="card flex flex-col gap-3 p-5 transition hover:border-canvas-muted/30 hover:shadow-soft"
          in:fly={{ y: 12, delay: 60 * i, duration: 320, easing: quintOut }}
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="truncate text-base font-semibold text-canvas-ink">{biz.name}</p>
              <p class="text-xs text-canvas-muted">{biz.city} · {biz.country}</p>
            </div>
            {#if biz.latest_grade}
              <span
                class={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${gradeToneClass[tone]}`}
                title={biz.latest_score != null ? `Score ${biz.latest_score}/100` : ''}
              >
                {biz.latest_grade}
                {#if arrow}
                  <span class={`text-[10px] ${trendToneClass[trendTone(biz.latest_trend)]} rounded-full px-1`}>
                    {arrow}
                  </span>
                {/if}
              </span>
            {/if}
          </div>

          {#if biz.running_audit_id}
            <p class="inline-flex items-center gap-1.5 text-xs font-medium text-healthy-700">
              <span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-healthy-500"></span>
              Health check in progress · watch it live →
            </p>
          {:else if biz.latest_audit_finished_at}
            <p class="text-xs text-canvas-muted">
              Last checked {formatRelativeTime(biz.latest_audit_finished_at)}
            </p>
            <span class="mt-auto inline-flex items-center gap-1 text-xs font-medium text-healthy-700">
              See latest health check →
            </span>
          {:else}
            <p class="text-xs text-canvas-muted">No health check yet.</p>
            <span class="mt-auto inline-flex items-center gap-1 text-xs font-medium text-healthy-700">
              Start a health check →
            </span>
          {/if}
        </a>
      {/each}
    </div>
    <div>
      <a class="btn-ghost" href="/">+ Add another business</a>
    </div>
  {/if}
</section>
