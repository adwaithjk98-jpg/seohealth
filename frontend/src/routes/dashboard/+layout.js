// Single fetch for /api/businesses shared across the Overview, Audit, and
// Competitors tabs. Each child page's data automatically merges the parent
// loader's output, so tab-switches no longer pay a fresh round-trip just
// to re-read the same business list.
//
// If a child needs additional data (e.g. /dashboard/competitors fans out
// for competitors), it stays in that page's own +page.js and reads
// businesses via ``await parent()``.

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
