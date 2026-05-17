// Tiny client-side auth state.
//
// Auth lives in three pieces:
//   - The browser holds an HttpOnly `session` cookie set by the backend.
//   - This module wraps the auth API calls and a Svelte 5 reactive store
//     (`authState`) that components can read.
//   - The root +layout.svelte calls `loadCurrentUser()` once on mount, then
//     individual pages or guards read `authState.user` synchronously.
//
// We keep this client-only on purpose — server-side fetches in SvelteKit's
// SSR mode would have to forward cookies through the dev proxy, which adds
// complexity for no real safety win (the backend enforces ownership).

import { goto } from '$app/navigation';

/**
 * @typedef {Object} TierLimits
 * @property {number} businesses
 * @property {number} audits_per_week
 * @property {number} [competitors]
 *
 * @typedef {Object} SubscriptionInfo
 * @property {number} id
 * @property {string} plan_tier
 * @property {string} status
 * @property {string | null} razorpay_subscription_id
 * @property {string | null} next_billing_date
 * @property {string | null} cancelled_at
 *
 * @typedef {Object} SubscriptionState
 * @property {string} tier
 * @property {TierLimits} limits
 * @property {number} business_count
 * @property {boolean} can_add_business
 * @property {SubscriptionInfo | null} subscription
 *
 * @typedef {Object} CurrentUser
 * @property {number} id
 * @property {string} email
 * @property {string} plan
 * @property {SubscriptionState | null} subscription_state
 */

/** @type {{ user: null | CurrentUser, loaded: boolean, loading: boolean }} */
export const authState = $state({
  user: null,
  loaded: false,
  loading: false
});

export async function refreshCurrentUser() {
  // Lighter sibling of loadCurrentUser — re-fetches after a state-changing
  // action (upgrade, business add) so the header / Add-business gates pick
  // up the new tier + business_count without a full page reload.
  try {
    const res = await fetch('/api/auth/session', { credentials: 'same-origin' });
    if (res.ok) {
      const body = await res.json();
      authState.user = body?.user ?? null;
    }
  } catch {
    /* leave user untouched on transient failure */
  }
  return authState.user;
}

/** @param {Response} res */
async function readJsonError(res) {
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (Array.isArray(data?.detail) && data.detail[0]?.msg) return data.detail[0].msg;
  } catch {
    /* fall through */
  }
  return `Request failed (${res.status})`;
}

export async function loadCurrentUser() {
  if (authState.loading) return authState.user;
  authState.loading = true;
  try {
    // /auth/session returns 200 with { user: null } when no valid session,
    // so the page-load probe doesn't fill the console with red 401s.
    const res = await fetch('/api/auth/session', { credentials: 'same-origin' });
    if (res.ok) {
      const body = await res.json();
      authState.user = body?.user ?? null;
    } else {
      // Transient 5xx → leave user untouched so we don't bounce to /login.
    }
  } catch {
    // network error — treat as not signed in
    authState.user = null;
  } finally {
    authState.loaded = true;
    authState.loading = false;
  }
  return authState.user;
}

/** @param {string} email */
export async function requestMagicLink(email) {
  const res = await fetch('/api/auth/request-link', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ email })
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

/** @param {string} token */
export async function verifyMagicLink(token) {
  const res = await fetch('/api/auth/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ token })
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  const user = await res.json();
  authState.user = user;
  authState.loaded = true;
  return user;
}

export async function logout() {
  await fetch('/api/auth/logout', { method: 'POST', credentials: 'same-origin' });
  authState.user = null;
  authState.loaded = true;
  await goto('/login');
}

// Routes the user can visit while signed out. Anything else bounces to
// /login when authState is loaded and user is null.
export const PUBLIC_ROUTES = ['/login', '/auth/verify'];

/** @param {string} pathname */
export function isPublicRoute(pathname) {
  return PUBLIC_ROUTES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}
