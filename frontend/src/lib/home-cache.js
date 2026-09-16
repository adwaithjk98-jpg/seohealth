// Persistence for the home payload — the part that makes the app open
// instantly instead of waiting on the network.
//
// Split out from `home.js` for two reasons: `auth.svelte.js` has to clear the
// cache on sign-in/sign-out and importing the loader there would make a
// cycle, and keeping the storage rules in one small file makes the privacy
// contract easy to audit:
//
//   - a signed-out payload is never written;
//   - the cache is dropped on logout and on magic-link verify, so one
//     account's businesses can never flash on screen for the next person to
//     sign in on the same device;
//   - a write that was started before a clear is discarded (see `generation`),
//     so a request in flight across a logout can't resurrect it;
//   - nothing older than a week is ever painted.
//
// Every access is wrapped: localStorage throws outright in some privacy modes,
// and a storage failure must never be the reason the app won't open.

/** Bump when the payload shape changes so old caches are ignored, not misread. */
const CACHE_KEY = 'seohealth:home:v1';

/** Never paint a cache older than this — a week-old score isn't a home screen. */
const MAX_CACHE_AGE_MS = 7 * 24 * 60 * 60 * 1000;

/**
 * Incremented by every `clearHomeCache()`. A fetch captures the generation it
 * started in and its write is dropped if the value moved on — which is what
 * stops a `/api/home` response that was already in flight when the user
 * signed out from writing that user's data back into storage.
 */
let _generation = 0;

/** Epoch ms of the last successful network read, in memory only: a fresh page
 *  load should always revalidate, however warm the stored copy is. */
let _lastFetchedAt = 0;

export function currentGeneration() {
  return _generation;
}

/**
 * True when the last network read is recent enough to reuse as-is.
 * @param {number} windowMs
 */
export function isFresh(windowMs) {
  return _lastFetchedAt > 0 && Date.now() - _lastFetchedAt < windowMs;
}

/** Force the next read to go to the network without discarding what's stored. */
export function markStale() {
  _lastFetchedAt = 0;
}

/**
 * The stored entry — `{ cachedAt, user, payload }` — or null when there is
 * nothing usable (absent, unreadable, userless, or too old).
 */
export function readHomeCache() {
  if (typeof localStorage === 'undefined') return null;
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) return null;
    const entry = JSON.parse(raw);
    if (!entry || typeof entry.cachedAt !== 'number' || !entry.user) return null;
    if (Date.now() - entry.cachedAt > MAX_CACHE_AGE_MS) {
      clearHomeCache();
      return null;
    }
    return entry;
  } catch {
    return null;
  }
}

/**
 * Store a payload for the next cold open.
 *
 * @param {{ businesses: any[] | null, heroAudit: any }} payload
 * @param {any} user  the signed-in user; a null user is never persisted
 * @param {number} generation  the value `currentGeneration()` returned when
 *   the fetch began — a stale generation means a clear happened meanwhile and
 *   this write is dropped
 */
export function writeHomeCache(payload, user, generation) {
  if (!user) return;
  if (generation !== _generation) return;
  _lastFetchedAt = Date.now();
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.setItem(
      CACHE_KEY,
      JSON.stringify({
        cachedAt: _lastFetchedAt,
        // The user is cached too, and re-seeded into `authState` on a cache
        // hit. Without it the root layout would still fire its session probe
        // on every open and we'd have traded a three-call open for a two-call
        // one.
        user,
        payload: {
          businesses: payload.businesses,
          heroAudit: payload.heroAudit,
          error: null
        }
      })
    );
  } catch {
    /* quota or private mode — the app works fine without a cache */
  }
}

/**
 * Drop the cached payload and force the next read to hit the network.
 *
 * Call this after anything that changes what the home screen should say:
 * signing out or in (so one account's data can never be painted for the
 * next), adding or archiving a business, changing plan, starting an audit.
 */
export function clearHomeCache() {
  _generation += 1;
  _lastFetchedAt = 0;
  if (typeof localStorage === 'undefined') return;
  try {
    localStorage.removeItem(CACHE_KEY);
  } catch {
    /* nothing we can do, and nothing that should break the caller */
  }
}
