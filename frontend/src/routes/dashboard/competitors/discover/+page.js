// Discovery loader. We need the user's businesses to:
//   1. Pick the anchor business (paid users can have multiple).
//   2. Group scraper results into "Found in <city>" vs "Found nearby" — the
//      city comes from the anchor business.
//
// We don't fetch the scan here. If the URL carries ?scan_id=N the +page.svelte
// polls it directly so the waiting state stays reactive — server-load-once
// would block the page on a 20-minute scan completing.

/** @type {import('@sveltejs/kit').Load} */
export async function load({ fetch }) {
  const res = await fetch('/api/businesses', { credentials: 'same-origin' });
  if (res.status === 401) {
    return { businesses: null, error: 'unauthenticated' };
  }
  if (!res.ok) {
    return { businesses: [], error: `Couldn't load your businesses (${res.status})` };
  }
  const businesses = await res.json();
  return { businesses, error: null };
}
