// Audit tab loader. We need the user's businesses to:
//   - Render the "Run manual audit" picker.
//   - Read each business's `next_auto_audit_at` for the Scheduled panel.
//
// Quota is a separate fetch from a +page.svelte effect (and re-fetched
// after a successful audit-start) so it stays fresh without forcing a
// full loader re-run.

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
