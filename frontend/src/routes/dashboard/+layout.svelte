<script>
  import { page } from '$app/stores';

  let { children } = $props();

  // Audit lives inside the per-business view today, so the Audit tab points
  // at the dashboard (where the user picks the business to audit). It still
  // lights up when the user is *inside* an audit or business detail view, so
  // they can see which mode they're in.
  const tabs = [
    { key: 'overview', label: 'Overview', href: '/dashboard' },
    { key: 'audit', label: 'Audit', href: '/dashboard' },
    { key: 'competitors', label: 'Competitors', href: '/dashboard/competitors' }
  ];

  const pathname = $derived($page.url.pathname);

  /** @param {string} key */
  function isActive(key) {
    if (key === 'competitors') return pathname.startsWith('/dashboard/competitors');
    if (key === 'audit') return pathname.startsWith('/audits') || pathname.startsWith('/businesses');
    if (key === 'overview') return pathname === '/dashboard' || pathname === '/dashboard/';
    return false;
  }
</script>

<div class="space-y-6">
  <nav
    class="-mx-4 flex gap-1 overflow-x-auto border-b border-canvas-soft px-4 sm:mx-0 sm:px-0"
    aria-label="Workspace sections"
  >
    {#each tabs as tab (tab.key)}
      {@const active = isActive(tab.key)}
      <a
        href={tab.href}
        class={`relative -mb-px inline-flex min-h-[40px] items-center whitespace-nowrap px-4 py-2 text-sm font-medium transition-colors duration-200 ${
          active
            ? 'text-canvas-ink'
            : 'text-canvas-muted hover:text-canvas-ink'
        }`}
        aria-current={active ? 'page' : undefined}
      >
        {tab.label}
        {#if active}
          <span class="absolute inset-x-3 -bottom-px h-0.5 rounded-full bg-healthy-500"></span>
        {/if}
      </a>
    {/each}
  </nav>

  {@render children()}
</div>
