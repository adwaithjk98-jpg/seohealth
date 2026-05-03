<script>
  import '../app.css';

  let { children } = $props();
</script>

<div class="min-h-screen bg-canvas">
  <header class="border-b border-canvas-soft bg-canvas/80 backdrop-blur">
    <div class="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
      <a href="/" class="flex items-center gap-2">
        <span
          class="grid h-8 w-8 place-items-center rounded-xl bg-healthy-500 text-white shadow-soft"
          aria-hidden="true"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            class="h-4 w-4"
          >
            <path d="M21 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
        </span>
        <span class="text-base font-semibold tracking-tight">Local SEO Health</span>
      </a>

      <nav class="flex items-center gap-1 text-sm">
        <a class="btn-ghost" href="/">Home</a>
        <a class="btn-ghost" href="/dashboard">Dashboard</a>
        <a class="btn-ghost" href="/help">Help</a>
      </nav>
    </div>
  </header>

  <main class="mx-auto max-w-5xl px-6 py-10">
    {@render children()}
  </main>

  <footer class="mx-auto max-w-5xl px-6 pb-10 pt-6 text-xs text-canvas-muted">
    A calm dashboard for your business's online presence.
  </footer>
</div>
