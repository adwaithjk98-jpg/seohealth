<script>
  import { page } from '$app/stores';

  const status = $derived($page.status);
  const isNotFound = $derived(status === 404);
  const detail = $derived($page.error?.message ?? '');
</script>

<section class="mx-auto mt-16 max-w-md space-y-5 text-center">
  <p class="text-5xl" aria-hidden="true">{isNotFound ? '🧭' : '🌧️'}</p>
  <h1 class="text-2xl font-semibold tracking-tight text-canvas-ink">
    {isNotFound ? "We couldn't find that page" : 'Something went sideways'}
  </h1>
  <p class="text-sm leading-relaxed text-canvas-muted">
    {#if isNotFound}
      The page you're after doesn't exist — it may have moved or the link was mistyped.
    {:else}
      We hit an unexpected error{detail ? ` (${detail})` : ''}. Refreshing usually sorts it.
    {/if}
  </p>
  <div class="flex flex-wrap justify-center gap-3">
    <a href="/dashboard" class="btn-primary">Back to dashboard</a>
    <a href="/" class="btn-ghost">Home</a>
  </div>
</section>
