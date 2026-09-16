// The cold-open path: one round trip, painted from cache first.
//
// Opening the app used to mean three *serial* network calls before anything
// could render — /api/businesses, then /api/businesses/{id}/latest-audit
// (gated behind `await parent()`), then /api/auth/session from the root
// layout's onMount. Three round trips against a 1-vCPU box is a blank screen
// for the sum of all three.
//
// Two changes live here:
//
//   1. **One request.** `/api/home` returns user + businesses + hero audit
//      together, so the waterfall collapses to a single call that also seeds
//      `authState` (the root layout's session probe then no-ops).
//
//   2. **Stale-while-revalidate.** The last good payload is kept in
//      localStorage (see `home-cache.js`). On open we paint it *synchronously*
//      — real score, real business name, no spinner — and refresh in the
//      background, swapping in fresh data when it lands. The app opens at
//      render speed instead of network speed.
//
// Freshness is surfaced, never faked: a payload served from cache carries
// `stale: true` and `cachedAt`, so the UI can say "showing your last check"
// rather than presenting old numbers as current.

import { invalidate } from '$app/navigation';
import { authState } from '$lib/auth.svelte.js';
import {
  clearHomeCache,
  currentGeneration,
  isFresh,
  markStale,
  readHomeCache,
  writeHomeCache
} from '$lib/home-cache.js';

/**
 * Within this window a payload counts as current and tab-switches reuse it
 * without touching the network. Long enough that moving between the dashboard
 * tabs is free, short enough that the app still feels live.
 */
const FRESH_WINDOW_MS = 10_000;

/** Load-function dependency key, so a finished background refresh can re-run
 *  the loaders via `invalidate(HOME_DEP)`. */
export const HOME_DEP = 'app:home';

/** Shared in-flight request so concurrent loaders join one fetch. */
let _inflight = /** @type {Promise<{ ok: boolean, payload: HomePayload }> | null} */ (null);

/**
 * When the last refresh failed to reach the server. While this is recent we
 * stop kicking new ones: a failed refresh still resolves, so invalidating on
 * it would re-run the loader, start another refresh, and spin — a retry loop
 * hammering a server that is already down.
 */
let _lastFailureAt = 0;

/** How long to sit still after a failed refresh before trying again. */
const RETRY_COOLDOWN_MS = 30_000;

/**
 * @typedef {Object} HomePayload
 * @property {any[] | null} businesses  null = signed out, [] = signed in with none
 * @property {any | null} heroAudit
 * @property {string | null} error      'unauthenticated' or a human message
 * @property {boolean} [stale]          true when served from cache
 * @property {number} [cachedAt]        epoch ms the cached copy was stored
 * @property {boolean} [offline]        cached copy shown after a failed refresh
 */

/**
 * Put the cached user into `authState` so the root layout's `onMount` probe
 * finds a loaded session and skips its round trip. The background refresh
 * overwrites this with the truth moments later — including setting it to null
 * and letting the route gate bounce to /login if the session has since died.
 * @param {any} user
 */
function seedAuthFromCache(user) {
  if (authState.loaded) return;
  authState.user = user;
  authState.loaded = true;
}

/**
 * Fetch `/api/home` and fold it into the shape the existing loaders return.
 *
 * `/api/home` never 401s — a dead session comes back as `user: null` — so the
 * "unauthenticated" signal the pages already branch on is reconstructed here,
 * keeping the `data.error` contract identical to the three-call version.
 *
 * Resolves `{ ok, payload }`. `ok` means the server actually answered — a
 * signed-out response counts, a dropped connection does not. Callers use it to
 * decide whether re-running the loaders is worth it: invalidating after a
 * failed fetch just starts the whole thing again, which is an infinite retry
 * loop against a server that is down.
 *
 * @param {typeof globalThis.fetch} fetchFn
 * @returns {Promise<{ ok: boolean, payload: HomePayload }>}
 */
async function fetchHome(fetchFn) {
  // Captured before the await so a logout mid-flight invalidates our write.
  const generation = currentGeneration();

  let res;
  try {
    res = await fetchFn('/api/home', { credentials: 'same-origin' });
  } catch {
    // Offline or a dropped connection. Leave any cache in place — the caller
    // may still be showing it, and that's better than an empty screen.
    return {
      ok: false,
      payload: { businesses: [], heroAudit: null, error: "Couldn't reach the server." }
    };
  }

  if (!res.ok) {
    return {
      ok: false,
      payload: {
        businesses: [],
        heroAudit: null,
        error: `Couldn't load your businesses (${res.status})`
      }
    };
  }

  const body = await res.json();
  const user = body?.user ?? null;

  // Seed the auth store from the same payload, so the root layout's session
  // probe finds the answer already there and skips its own round trip.
  authState.user = user;
  authState.loaded = true;

  if (!user) {
    // Session is gone. Whatever we had cached belonged to someone who is no
    // longer signed in here — drop it before it can be painted again.
    clearHomeCache();
    return {
      ok: true,
      payload: { businesses: null, heroAudit: null, error: 'unauthenticated' }
    };
  }

  /** @type {HomePayload} */
  const payload = {
    businesses: body?.businesses ?? [],
    heroAudit: body?.hero_audit ?? null,
    error: null
  };
  writeHomeCache(payload, user, generation);
  return { ok: true, payload };
}

/** @param {typeof globalThis.fetch} fetchFn */
function refresh(fetchFn) {
  if (_inflight) return _inflight;
  _inflight = fetchHome(fetchFn).finally(() => {
    _inflight = null;
  });
  return _inflight;
}

/**
 * Force a network read of the home payload and update the cache.
 * Used by callers that just changed something and want the truth now.
 * @param {typeof globalThis.fetch} [fetchFn]
 */
export function refreshHome(fetchFn = globalThis.fetch) {
  markStale();
  return refresh(fetchFn).then((r) => r.payload);
}

/**
 * Stale-while-revalidate read used by `dashboard/+layout.js`.
 *
 * Returns synchronously (no await) whenever a usable cache exists, which is
 * what makes the app paint instantly; the network refresh runs behind it and
 * re-runs the loaders through `invalidate(HOME_DEP)` once fresh data lands.
 *
 * @param {import('@sveltejs/kit').LoadEvent} event
 * @returns {HomePayload | Promise<HomePayload>}
 */
export function loadHome({ fetch, depends }) {
  depends(HOME_DEP);

  const entry = readHomeCache();

  // Read from the network a moment ago — a tab switch, or the re-run
  // triggered by a just-finished refresh. The cache *is* current.
  if (entry && isFresh(FRESH_WINDOW_MS)) {
    seedAuthFromCache(entry.user);
    return { ...entry.payload, stale: false };
  }

  if (entry) {
    seedAuthFromCache(entry.user);

    const cooling = _lastFailureAt > 0 && Date.now() - _lastFailureAt < RETRY_COOLDOWN_MS;
    if (!cooling) {
      // Paint the known-good copy now; swap in the truth when it arrives —
      // fresh data, or the signed-out payload that bounces us to /login.
      refresh(fetch)
        .then(({ ok }) => {
          _lastFailureAt = ok ? 0 : Date.now();
          // Re-runs the loader either way: on success to show fresh data, on
          // failure to swap the "refreshing…" note for an honest offline one.
          // The cooldown above is what stops that re-run from looping.
          invalidate(HOME_DEP);
        })
        .catch(() => {
          /* keep showing the cached copy */
        });
    }

    return {
      ...entry.payload,
      stale: true,
      cachedAt: entry.cachedAt,
      offline: cooling
    };
  }

  // First open on this device — nothing to paint but the spinner.
  return refresh(fetch).then((r) => r.payload);
}
