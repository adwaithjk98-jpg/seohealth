<script>
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { fade } from 'svelte/transition';

  import { authState, loadCurrentUser } from '$lib/auth.svelte.js';
  import { getAdminStats } from '$lib/api.js';
  import { reduced } from '$lib/motion.js';
  import Skeleton from '$lib/components/Skeleton.svelte';

  /** @type {any} */
  let stats = $state(null);
  let loading = $state(true);
  let error = $state(/** @type {string | null} */ (null));

  onMount(async () => {
    if (!authState.loaded) await loadCurrentUser();
    if (!authState.user) {
      await goto('/login', { replaceState: true });
      return;
    }
    // Server enforces this too (404s non-admins); this just avoids a pointless
    // fetch + bounces a curious non-admin back to their dashboard.
    if (!authState.user.is_admin) {
      await goto('/dashboard', { replaceState: true });
      return;
    }
    try {
      stats = await getAdminStats();
    } catch (err) {
      error = err instanceof Error ? err.message : 'Could not load stats.';
    } finally {
      loading = false;
    }
  });

  /** @param {number | null | undefined} pct */
  function tone(pct) {
    // For "free %" headroom: green plenty, amber getting tight, coral low.
    if (pct == null) return 'text-canvas-muted';
    if (pct >= 40) return 'text-healthy-700';
    if (pct >= 20) return 'text-attention-700';
    return 'text-action-700';
  }

  const inr = (/** @type {number} */ n) => '₹' + n.toLocaleString('en-IN');
</script>

<svelte:head><title>Stats · SEO Health</title></svelte:head>

<section class="space-y-6">
  <header>
    <p
      class="inline-flex items-center gap-2 rounded-full border border-canvas-soft bg-canvas-soft/50 px-3 py-1 text-xs font-medium text-canvas-muted"
    >
      <span class="h-1.5 w-1.5 rounded-full bg-canvas-muted"></span>
      Founder · internal
    </p>
    <h1 class="mt-3 text-3xl font-semibold tracking-tight text-canvas-ink sm:text-4xl">
      Stats
    </h1>
    {#if stats}
      <p class="mt-1 text-xs text-canvas-muted">
        As of {new Date(stats.as_of + 'Z').toLocaleString()}
      </p>
    {/if}
  </header>

  {#if loading}
    <div class="grid gap-4 sm:grid-cols-2" aria-busy="true">
      <Skeleton height="h-36" width="w-full" rounded="2xl" />
      <Skeleton height="h-36" width="w-full" rounded="2xl" />
      <Skeleton height="h-36" width="w-full" rounded="2xl" />
      <Skeleton height="h-36" width="w-full" rounded="2xl" />
    </div>
  {:else if error}
    <div class="card border border-action-100 bg-action-50 p-6 text-sm text-action-700">
      <p class="font-medium">Couldn't load stats.</p>
      <p class="mt-1 text-action-700/80">{error}</p>
    </div>
  {:else if stats}
    <div class="grid gap-4 sm:grid-cols-2" in:fade={reduced({ duration: 200 })}>
      <!-- Users -->
      <div class="card p-5">
        <p class="text-xs uppercase tracking-wide text-canvas-muted">Users</p>
        <p class="mt-1 text-3xl font-semibold text-canvas-ink">{stats.users.total}</p>
        <p class="mt-2 text-sm text-canvas-ink">
          {stats.users.free} free · <span class="text-healthy-700">{stats.users.pro} Pro</span> ·
          <span class="text-attention-700">{stats.users.max} Max</span>
        </p>
        <p class="mt-1 text-xs text-canvas-muted">
          {stats.users.conversion_pct}% paid conversion
        </p>
      </div>

      <!-- Revenue -->
      <div class="card p-5">
        <p class="text-xs uppercase tracking-wide text-canvas-muted">MRR (est.)</p>
        <p class="mt-1 text-3xl font-semibold text-canvas-ink">{inr(stats.revenue.mrr_inr)}</p>
        <p class="mt-2 text-sm text-canvas-muted">
          {stats.revenue.active_subscriptions} active subscriptions
        </p>
        <p class="mt-1 text-xs text-canvas-muted">Razorpay dashboard is the source of truth</p>
      </div>

      <!-- Growth -->
      <div class="card p-5">
        <p class="text-xs uppercase tracking-wide text-canvas-muted">Growth</p>
        <p class="mt-1 text-sm text-canvas-ink">
          <span class="text-2xl font-semibold">{stats.growth.signups_7d}</span> signups · 7d
        </p>
        <p class="mt-1 text-xs text-canvas-muted">
          {stats.growth.signups_30d} in 30d · {stats.growth.audits_7d} audits run in 7d
        </p>
      </div>

      <!-- Queue (2nd-worker trigger) -->
      <div class="card p-5">
        <p class="text-xs uppercase tracking-wide text-canvas-muted">Audit queue depth</p>
        <p class="mt-1 text-3xl font-semibold {tone(stats.queue_depth.audits === 0 ? 100 : 10)}">
          {stats.queue_depth.audits ?? '—'}
        </p>
        <p class="mt-1 text-xs text-canvas-muted">
          competitors: {stats.queue_depth.competitors ?? '—'} · if this stays &gt;0 between ticks,
          add a 2nd worker
        </p>
      </div>

      <!-- Server (the real upgrade trigger) -->
      <div class="card p-5 sm:col-span-2">
        <p class="text-xs uppercase tracking-wide text-canvas-muted">
          Server headroom — the real "upgrade in time" signal
        </p>
        <div class="mt-2 grid grid-cols-3 gap-3 text-center">
          <div>
            <p class="text-2xl font-semibold {tone(stats.server.ram_free_pct)}">
              {stats.server.ram_free_pct ?? '—'}{stats.server.ram_free_pct != null ? '%' : ''}
            </p>
            <p class="text-xs text-canvas-muted">RAM free</p>
          </div>
          <div>
            <p class="text-2xl font-semibold text-canvas-ink">
              {stats.server.load_avg_1m ?? '—'}
            </p>
            <p class="text-xs text-canvas-muted">load (1m)</p>
          </div>
          <div>
            <p class="text-2xl font-semibold {tone(stats.server.disk_free_pct)}">
              {stats.server.disk_free_pct ?? '—'}{stats.server.disk_free_pct != null ? '%' : ''}
            </p>
            <p class="text-xs text-canvas-muted">disk free</p>
          </div>
        </div>
        <p class="mt-3 text-xs text-canvas-muted">
          Chrome/Selenium is the RAM hog. When RAM-free trends low or load stays high during
          audits, bump CX22 → CX32 — don't wait for a user-count milestone. (RAM shows on the
          Linux server; blank in local dev.)
        </p>
      </div>
    </div>
  {/if}
</section>
