// Deep-dive loader.
//
// The page itself is *competitor-first*: by default it shows only this
// competitor's metrics over time. Comparison against the user's own
// businesses is an opt-in pill on the page. To make that picker snappy
// (no fetch on toggle), we pull every business's trends payload up
// front. Paid users cap at 3 businesses, so the fan-out is bounded.

/** @type {import('@sveltejs/kit').Load} */
export async function load({ fetch, params }) {
  const businessId = Number(params.id);
  const competitorId = Number(params.competitor_id);

  const [bizListRes, compsRes] = await Promise.all([
    fetch('/api/businesses', { credentials: 'same-origin' }),
    fetch(`/api/businesses/${businessId}/competitors`, { credentials: 'same-origin' })
  ]);

  if (bizListRes.status === 401 || compsRes.status === 401) {
    return {
      business: null,
      competitor: null,
      anchorTrends: null,
      businessTrends: {},
      businesses: [],
      error: 'unauthenticated'
    };
  }
  if (!bizListRes.ok) {
    return {
      business: null,
      competitor: null,
      anchorTrends: null,
      businessTrends: {},
      businesses: [],
      error: `Couldn't load your businesses (${bizListRes.status})`
    };
  }
  if (!compsRes.ok) {
    return {
      business: null,
      competitor: null,
      anchorTrends: null,
      businessTrends: {},
      businesses: [],
      error: `Couldn't load competitors (${compsRes.status})`
    };
  }

  const businesses = await bizListRes.json();
  const business = businesses.find((/** @type {any} */ b) => b.id === businessId) ?? null;
  if (!business) {
    return {
      business: null,
      competitor: null,
      anchorTrends: null,
      businessTrends: {},
      businesses,
      error: 'Business not found.'
    };
  }
  const competitors = await compsRes.json();
  const competitor = competitors.find((/** @type {any} */ c) => c.id === competitorId) ?? null;

  if (!competitor) {
    return {
      business,
      competitor: null,
      anchorTrends: null,
      businessTrends: {},
      businesses,
      error: 'Competitor not found.'
    };
  }

  // Fan out to every business's /trends so the Compare-against picker
  // can swap series instantly. Failures on individual businesses don't
  // sink the page — that business just won't be selectable.
  const trendsSettled = await Promise.allSettled(
    businesses.map(async (/** @type {any} */ b) => {
      const res = await fetch(`/api/businesses/${b.id}/trends`, {
        credentials: 'same-origin'
      });
      if (!res.ok) throw new Error(`trends ${res.status}`);
      const trends = await res.json();
      return { businessId: b.id, trends };
    })
  );

  /** @type {Record<number, any>} */
  const businessTrends = {};
  for (const r of trendsSettled) {
    if (r.status === 'fulfilled') {
      businessTrends[r.value.businessId] = r.value.trends;
    }
  }

  // The anchor business's trends payload is the canonical source for
  // *this* competitor's observation series — every business's trends
  // payload includes that business's own line plus its competitors'
  // observations, so we pluck the competitor out of the anchor's.
  const anchorTrends = businessTrends[businessId] ?? { business: [], competitors: [] };

  return {
    business,
    competitor,
    anchorTrends,
    businessTrends,
    businesses,
    error: null
  };
}
