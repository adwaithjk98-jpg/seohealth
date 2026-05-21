// Market Comparison loader. Fans out to /trends and /competitors for
// every business the user owns, since both endpoints are per-business
// and the market view stacks everyone together.
//
// Failures on individual businesses don't sink the whole page — we drop
// that business from the aggregate and report the error count to the UI.

/** @type {import('@sveltejs/kit').Load} */
export async function load({ fetch }) {
  const bizRes = await fetch('/api/businesses', { credentials: 'same-origin' });
  if (bizRes.status === 401) {
    return {
      businesses: null,
      bundles: [],
      error: 'unauthenticated'
    };
  }
  if (!bizRes.ok) {
    return {
      businesses: [],
      bundles: [],
      error: `Couldn't load your businesses (${bizRes.status})`
    };
  }
  const businesses = await bizRes.json();

  const settled = await Promise.allSettled(
    businesses.map(async (/** @type {any} */ biz) => {
      const [trendsRes, compsRes] = await Promise.all([
        fetch(`/api/businesses/${biz.id}/trends`, { credentials: 'same-origin' }),
        fetch(`/api/businesses/${biz.id}/competitors`, { credentials: 'same-origin' })
      ]);
      if (!trendsRes.ok) throw new Error(`trends ${trendsRes.status}`);
      if (!compsRes.ok) throw new Error(`competitors ${compsRes.status}`);
      const trends = await trendsRes.json();
      const competitors = await compsRes.json();
      return { business: biz, trends, competitors };
    })
  );

  /** @type {any[]} */
  const bundles = [];
  for (const result of settled) {
    if (result.status === 'fulfilled') bundles.push(result.value);
  }

  return { businesses, bundles, error: null };
}
