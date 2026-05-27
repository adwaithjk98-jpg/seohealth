// Competitor Hub loader. Reads the user's businesses from the parent
// dashboard loader (so a tab-switch doesn't re-fetch /api/businesses) and
// fans out to /api/businesses/{id}/competitors per business.
//
// Paid users cap at 3 businesses, so the fan-out is bounded and trivially
// small. If that limit ever grows, this is the place to swap in a
// dedicated aggregator route.

/** @type {import('@sveltejs/kit').Load} */
export async function load({ fetch, parent }) {
  const { businesses, error } = await parent();
  if (error === 'unauthenticated') {
    return { businesses: null, competitors: [], error: 'unauthenticated' };
  }
  if (!businesses || businesses.length === 0) {
    return { businesses: businesses ?? [], competitors: [], error };
  }

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

  return { businesses, competitors, error: null };
}
