// Deep-dive loader. Three parallel fetches: the business (for name +
// city), the competitor list (to pick the one we're diving into), and
// the trends payload (the 1-on-1 chart and the Reviews-tab math).
//
// The competitor list endpoint is per-business and tiny (≤3 rows), so
// we filter client-side rather than adding a get-one endpoint.

/** @type {import('@sveltejs/kit').Load} */
export async function load({ fetch, params }) {
  const businessId = Number(params.id);
  const competitorId = Number(params.competitor_id);

  // There's no per-business detail endpoint; the list is small (≤3 for
  // paid users) so we fetch it and pluck the one we need.
  const [bizListRes, compsRes, trendsRes] = await Promise.all([
    fetch('/api/businesses', { credentials: 'same-origin' }),
    fetch(`/api/businesses/${businessId}/competitors`, { credentials: 'same-origin' }),
    fetch(`/api/businesses/${businessId}/trends`, { credentials: 'same-origin' })
  ]);

  if (bizListRes.status === 401 || compsRes.status === 401 || trendsRes.status === 401) {
    return { business: null, competitor: null, trends: null, error: 'unauthenticated' };
  }
  if (!bizListRes.ok) {
    return {
      business: null,
      competitor: null,
      trends: null,
      error: `Couldn't load your businesses (${bizListRes.status})`
    };
  }
  if (!compsRes.ok) {
    return {
      business: null,
      competitor: null,
      trends: null,
      error: `Couldn't load competitors (${compsRes.status})`
    };
  }

  const businesses = await bizListRes.json();
  const business = businesses.find((/** @type {any} */ b) => b.id === businessId) ?? null;
  if (!business) {
    return { business: null, competitor: null, trends: null, error: 'Business not found.' };
  }
  const competitors = await compsRes.json();
  const competitor = competitors.find((/** @type {any} */ c) => c.id === competitorId) ?? null;

  if (!competitor) {
    return {
      business,
      competitor: null,
      trends: null,
      error: 'Competitor not found.'
    };
  }

  const trends = trendsRes.ok ? await trendsRes.json() : { business: [], competitors: [] };
  return { business, competitor, trends, error: null };
}
