// Cross-business "all your insights" view. Fans out /latest-audit for
// every business in the layout's businesses payload and surfaces every
// open recommendation, grouped by business. Mark-as-done is not handled
// here — rec rows link to the per-finding page where the existing
// PATCH /api/recommendations/{id} flow lives, so the two views share
// one source of truth and never drift.

import { topOpenRecommendations } from '$lib/dashboard.js';

/** @type {import('@sveltejs/kit').Load} */
export async function load({ fetch, parent }) {
  const parentData = await parent();

  if (parentData?.error === 'unauthenticated') {
    return { groups: [], totalOpen: 0, totalDone: 0, error: 'unauthenticated' };
  }

  const businesses = parentData?.businesses ?? [];
  if (businesses.length === 0) {
    return { groups: [], totalOpen: 0, totalDone: 0, error: null };
  }

  const settled = await Promise.allSettled(
    businesses.map(async (/** @type {any} */ b) => {
      const res = await fetch(`/api/businesses/${b.id}/latest-audit`, {
        credentials: 'same-origin'
      });
      // 404 here just means the business has no completed audit yet —
      // not an error worth surfacing. Skip it silently.
      if (res.status === 404) return { business: b, audit: null };
      if (!res.ok) throw new Error(`status ${res.status}`);
      return { business: b, audit: await res.json() };
    })
  );

  /** @type {Array<{
   *   business: any,
   *   auditId: number | null,
   *   openCount: number,
   *   doneCount: number,
   *   recommendations: any[]
   * }>} */
  const groups = [];
  let totalOpen = 0;
  let totalDone = 0;
  for (const r of settled) {
    if (r.status !== 'fulfilled') continue;
    const { business, audit } = r.value;
    const sections = (audit?.sections ?? []).filter(
      (/** @type {any} */ s) => s.enabled !== false
    );
    const recs = topOpenRecommendations(sections, Number.POSITIVE_INFINITY);
    const openCount = audit?.open_recommendations_count ?? recs.length;
    const doneCount = audit?.done_recommendations_count ?? 0;
    groups.push({
      business,
      auditId: audit?.audit_id ?? null,
      openCount,
      doneCount,
      recommendations: recs
    });
    totalOpen += recs.length;
    totalDone += doneCount;
  }

  // Surface businesses with open work first, then businesses that are
  // caught up. Within each band, preserve the input order so the page
  // matches the dashboard grid layout.
  groups.sort((a, b) => {
    if ((a.recommendations.length > 0) !== (b.recommendations.length > 0)) {
      return a.recommendations.length > 0 ? -1 : 1;
    }
    return 0;
  });

  return { groups, totalOpen, totalDone, error: null };
}
