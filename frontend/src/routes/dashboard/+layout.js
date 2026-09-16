// One read for every dashboard surface.
//
// This used to fetch /api/businesses, and the Overview page then fetched the
// hero audit *after* it via `await parent()` — two serial round trips before
// the home screen could paint, plus the root layout's session probe as a
// third. `/api/home` returns all three payloads together, and `loadHome`
// serves the last-known copy from cache while it revalidates, so the app
// opens at render speed rather than network speed.
//
// The returned shape is unchanged (`businesses` / `error`, plus `heroAudit`
// which the Overview page reads off merged layout data), so every child page
// consuming `data.businesses` keeps working exactly as before.

import { loadHome } from '$lib/home.js';

/** @type {import('@sveltejs/kit').Load} */
export function load(event) {
  return loadHome(event);
}
