// Single fetch for /api/businesses per navigation — SvelteKit caches the
// loader's result for the page lifetime, so the dashboard no longer
// double-fetches on render (m4 in the walkthrough). SSR/prerender are
// already off at the layout level.

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
