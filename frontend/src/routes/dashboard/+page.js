// Home loader. The overview leads with status for single-business users
// (score ring, since-last-check, the one move this week), which needs the
// latest completed audit — one bounded fetch, only in the one-business
// case. Multi-business (Max) accounts keep the per-business grid and skip
// the extra round-trip entirely.

/** @type {import('@sveltejs/kit').Load} */
export async function load({ fetch, parent }) {
  const parentData = await parent();
  const businesses = parentData?.businesses ?? [];
  if (
    parentData?.error ||
    businesses.length !== 1 ||
    businesses[0].latest_audit_id == null
  ) {
    return { heroAudit: null };
  }
  try {
    const res = await fetch(`/api/businesses/${businesses[0].id}/latest-audit`, {
      credentials: 'same-origin'
    });
    if (!res.ok) return { heroAudit: null };
    return { heroAudit: await res.json() };
  } catch {
    // Network blip — the page falls back to the business-card view, which
    // renders fine from the layout's businesses payload alone.
    return { heroAudit: null };
  }
}
