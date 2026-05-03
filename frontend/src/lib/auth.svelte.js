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

/** @type {{ user: null | { id: number, email: string, plan: string }, loaded: boolean, loading: boolean }} */
export const authState = $state({
  user: null,
  loaded: false,
  loading: false
});

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
    const res = await fetch('/api/auth/me', { credentials: 'same-origin' });
    if (res.status === 401) {
      authState.user = null;
    } else if (res.ok) {
      authState.user = await res.json();
    } else {
      // Anything other than 401/200 — leave user untouched, surface no error.
      // (We're loading on every layout mount; transient 5xx shouldn't bounce
      // the user to /login.)
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
