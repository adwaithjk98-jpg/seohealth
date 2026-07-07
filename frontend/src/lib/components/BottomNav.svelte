<script>
  import { page } from '$app/stores';

  /**
   * Persistent bottom tab bar — mobile only (`sm:hidden`). The workspace
   * pill inside /dashboard/* vanishes the moment the user drills into a
   * business, an audit, or a finding, which left deep pages with no
   * thumb-reachable wayfinding on the primary device. This bar stays put
   * on every signed-in app surface; the root layout decides when to
   * render it (never for signed-out or public/legal routes).
   *
   * Tabs mirror the dashboard's segmented control — same three
   * destinations, same active logic — so the two navs never disagree.
   */

  const pathname = $derived($page.url.pathname);

  /** @type {Array<{ key: string, label: string, href: string }>} */
  const tabs = [
    { key: 'home', label: 'Home', href: '/dashboard' },
    { key: 'audit', label: 'Audits', href: '/dashboard/audit' },
    { key: 'competitors', label: 'Competitors', href: '/dashboard/competitors' }
  ];

  /** @param {string} key */
  function isActive(key) {
    if (key === 'competitors') {
      return (
        pathname.startsWith('/dashboard/competitors') ||
        /^\/businesses\/[^/]+\/competitors/.test(pathname)
      );
    }
    if (key === 'audit') {
      return (
        pathname.startsWith('/dashboard/audit') ||
        pathname.startsWith('/audits') ||
        (pathname.startsWith('/businesses') &&
          !/^\/businesses\/[^/]+\/competitors/.test(pathname))
      );
    }
    if (key === 'home') {
      return (
        pathname === '/dashboard' ||
        pathname === '/dashboard/' ||
        pathname.startsWith('/dashboard/insights') ||
        pathname.startsWith('/weekly-insights')
      );
    }
    return false;
  }
</script>

<nav
  class="fixed inset-x-0 bottom-0 z-40 border-t border-canvas-soft bg-canvas/90 backdrop-blur sm:hidden"
  style="padding-bottom: env(safe-area-inset-bottom);"
  aria-label="Primary"
  data-sveltekit-preload-code="viewport"
  data-sveltekit-preload-data="tap"
>
  <div class="mx-auto flex max-w-5xl">
    {#each tabs as tab (tab.key)}
      {@const active = isActive(tab.key)}
      <a
        href={tab.href}
        aria-current={active ? 'page' : undefined}
        class="flex min-h-[56px] flex-1 flex-col items-center justify-center gap-0.5 text-[11px] font-medium"
      >
        <span
          class={`grid h-7 w-12 place-items-center rounded-full transition-colors duration-200 ${
            active ? 'bg-healthy-100 text-healthy-800' : 'text-canvas-muted'
          }`}
          aria-hidden="true"
        >
          {#if tab.key === 'home'}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="h-5 w-5"
            >
              <path d="M3 10.5 12 3l9 7.5" />
              <path d="M5 9.5V20a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1V9.5" />
            </svg>
          {:else if tab.key === 'audit'}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="h-5 w-5"
            >
              <rect x="3" y="3" width="7" height="7" rx="1.5" />
              <rect x="14" y="3" width="7" height="7" rx="1.5" />
              <rect x="3" y="14" width="7" height="7" rx="1.5" />
              <rect x="14" y="14" width="7" height="7" rx="1.5" />
            </svg>
          {:else}
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="h-5 w-5"
            >
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
          {/if}
        </span>
        <span class={active ? 'text-healthy-800' : 'text-canvas-muted'}>{tab.label}</span>
      </a>
    {/each}
  </div>
</nav>
