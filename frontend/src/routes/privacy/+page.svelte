<script>
  // Canonical redirect. These policies used to be maintained a second time
  // here, in-app, and they drifted from the published ones on seohealth.in —
  // at one point promising a 7-day refund the site policy did not offer. Two
  // contradictory published policies is worse than an extra hop, so the app
  // now owns no policy text at all and forwards to the single canonical copy.
  //
  // The route is kept (rather than deleted) so existing links, bookmarks and
  // anything that recorded an app policy URL keep resolving instead of 404ing.
  import { onMount } from 'svelte';

  const canonical = 'https://seohealth.in/privacy';

  onMount(() => {
    // replace(), not href: otherwise Back lands here and bounces straight out
    // again, trapping the user in a redirect loop.
    window.location.replace(canonical);
  });
</script>

<svelte:head>
  <title>Privacy Policy · SEO Health</title>
  <meta http-equiv="refresh" content="0; url=https://seohealth.in/privacy" />
  <link rel="canonical" href="https://seohealth.in/privacy" />
</svelte:head>

<section class="mx-auto max-w-md py-16 text-center">
  <p class="text-sm text-canvas-muted">Opening our Privacy Policy…</p>
  <p class="mt-3 text-sm">
    <a class="font-medium text-healthy-700 hover:underline" href={canonical}>
      Continue to the Privacy Policy
    </a>
  </p>
</section>
