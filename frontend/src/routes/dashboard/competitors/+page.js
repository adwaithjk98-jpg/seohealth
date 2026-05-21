// Competitor Hub loader. Aggregates active competitors across every
// business the user owns, since the backend stores them per-business but
// the hub is a single top-level view.
//
// We do a fan-out fetch (one /competitors call per business) rather than
// add a new backend endpoint — paid users cap at 3 businesses, so the
// fan-out is bounded and trivially small. If that limit ever grows, this
// is the place to swap in a dedicated aggregator route.

/** @type {import('@sveltejs/kit').Load} */
export async function load({ fetch }) {
  const bizRes = await fetch('/api/businesses', { credentials: 'same-origin' });
  if (bizRes.status === 401) {
    return {
      businesses: null,
      competitors: [],
      error: 'unauthenticated'
    };
  }
  if (!bizRes.ok) {
    return {
      businesses: [],
      competitors: [],
      error: `Couldn't load your businesses (${bizRes.status})`
    };
  }
  const businesses = await bizRes.json();

  // Fan out. Failures on individual businesses don't sink the whole page;
  // we just drop that business from the aggregate and let the user retry.
  const settled = await Promise.allSettled(
    businesses.map(async (/** @type {any} */ biz) => {
      const res = await fetch(`/api/businesses/${biz.id}/competitors`, {
        credentials: 'same-origin'
      });
      if (!res.ok) throw new Error(`competitors ${res.status}`);
      const rows = await res.json();
      return rows.map((/** @type {any} */ c) => ({
        ...c,
        business_id: biz.id,
        business_name: biz.name,
        business_city: biz.city
      }));
    })
  );

  /** @type {any[]} */
  const competitors = [];
  for (const result of settled) {
    if (result.status === 'fulfilled') {
      competitors.push(...result.value);
    }
  }

  return {
    businesses,
    competitors,
    error: null
  };
}
