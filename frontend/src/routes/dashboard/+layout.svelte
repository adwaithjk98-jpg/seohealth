<script>
  import { page } from '$app/stores';

  let { children } = $props();

  // Phase 4.7 — the Audit tab now has its own dedicated route. The
  // Overview tab keeps the dashboard summary (business list). The Audit
  // tab is the management surface (quota, manual run, scheduled).
  /** @type {Array<{ key: string, label: string, href: string, icon: string }>} */
  const tabs = [
    { key: 'overview', label: 'Overview', href: '/dashboard', icon: 'home' },
    { key: 'audit', label: 'Audit', href: '/dashboard/audit', icon: 'grid' },
    {
      key: 'competitors',
      label: 'Competitors',
      href: '/dashboard/competitors',
      icon: 'users'
    }
  ];

  const pathname = $derived($page.url.pathname);

  /** @param {string} key */
  function isActive(key) {
    if (key === 'competitors') return pathname.startsWith('/dashboard/competitors');
    // Audit lights up on its own route AND inside any in-progress
    // audit view, so the user always knows which mode they're in.
    if (key === 'audit') {
      return (
        pathname.startsWith('/dashboard/audit') ||
        pathname.startsWith('/audits') ||
        pathname.startsWith('/businesses')
      );
    }
    if (key === 'overview') {
      return (
        pathname === '/dashboard' ||
        pathname === '/dashboard/' ||
        pathname.startsWith('/dashboard/insights')
      );
    }
    return false;
  }
</script>

<div class="space-y-6">
  <!--
    Segmented-pill tab nav. Each tab is ``flex-1`` so the three options
    distribute evenly across the available width — no trailing empty
    rail like the old underline-style nav had. Active tab gets a white
    pill with a soft shadow, inactive tabs sit on the container's tinted
    background.

    Preloading: ``preload-code="viewport"`` warms each tab's JS chunk as
    soon as the nav is visible (kills the cold Vite-import pause on first
    tap), and ``preload-data="tap"`` fires the tab's loader the moment a
    finger touches the link — on touch devices the SvelteKit default of
    ``hover`` is a no-op.
  -->
  <nav
    class="flex items-center gap-1 rounded-2xl border border-canvas-soft bg-canvas-soft/40 p-1"
    aria-label="Workspace sections"
    data-sveltekit-preload-code="viewport"
    data-sveltekit-preload-data="tap"
  >
    {#each tabs as tab (tab.key)}
      {@const active = isActive(tab.key)}
      <a
        href={tab.href}
        class={`inline-flex flex-1 items-center justify-center gap-2 rounded-xl px-3 py-2 text-sm font-medium transition-colors duration-200 ${
          active
            ? 'bg-white text-canvas-ink shadow-soft'
            : 'text-canvas-muted hover:text-canvas-ink'
        }`}
        aria-current={active ? 'page' : undefined}
      >
        <span class="grid h-4 w-4 shrink-0 place-items-center" aria-hidden="true">
          {#if tab.icon === 'home'}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="h-4 w-4"
            >
              <path d="M3 10.5 12 3l9 7.5" />
              <path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5" />
            </svg>
          {:else if tab.icon === 'grid'}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="h-4 w-4"
            >
              <rect x="3" y="3" width="7" height="7" rx="1.5" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" />
            </svg>
          {:else if tab.icon === 'users'}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="h-4 w-4"
            >
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
          {/if}
        </span>
        {tab.label}
      </a>
    {/each}
  </nav>

  {@render children()}
</div>
