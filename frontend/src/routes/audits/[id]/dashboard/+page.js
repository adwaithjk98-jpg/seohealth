// /audits/{id}/dashboard used to be a near-line-for-line copy of the
// canonical /businesses/{id} view — same gauge, pillars, and top-3, minus
// the newer banners (they'd already drifted apart). The route survives as
// a redirect so old bookmarks and the PWA's cached URLs keep working; the
// business page always shows the latest completed snapshot, which is what
// this URL resolved to in practice the moment a newer audit ran.

import { redirect } from '@sveltejs/kit';

/** @type {import('@sveltejs/kit').Load} */
export async function load({ fetch, params }) {
  try {
    const res = await fetch(`/api/audits/${params.id}`, { credentials: 'same-origin' });
    if (res.ok) {
      const audit = await res.json();
      const businessId = audit?.business?.id;
      if (businessId != null) {
        redirect(307, `/businesses/${businessId}`);
      }
    }
  } catch (err) {
    // redirect() throws on purpose — let it through; swallow only real
    // fetch failures and fall back to the workspace home below.
    if (err && typeof err === 'object' && 'status' in err && 'location' in err) throw err;
  }
  redirect(307, '/dashboard');
}
