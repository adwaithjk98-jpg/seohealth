// Web Push subscription helpers for the PWA.
//
// Push state is *device-local*: it reflects this browser's PushSubscription,
// not a server-side flag. The account toggle reads getPushState() on mount and
// calls enablePush() / disablePush(). The backend only stores the subscription
// so it can send (scheduled-audit-done, competitor-moved). The VAPID public key
// is fetched from the API so the backend stays the single source of truth.

import { getVapidPublicKey, subscribePush, unsubscribePush } from '$lib/api.js';

/** Standard base64url → Uint8Array for applicationServerKey. */
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
  const raw = atob(base64);
  const output = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) output[i] = raw.charCodeAt(i);
  return output;
}

export function isPushSupported() {
  return (
    typeof window !== 'undefined' &&
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  );
}

/**
 * Snapshot of this device's push state for the account toggle.
 * `available` means the backend has a VAPID key (push actually works);
 * `subscribed` means this browser already has a live subscription.
 * @returns {Promise<{ supported: boolean, available: boolean, permission: NotificationPermission, subscribed: boolean }>}
 */
export async function getPushState() {
  if (!isPushSupported()) {
    return { supported: false, available: false, permission: 'denied', subscribed: false };
  }
  let available = false;
  try {
    const { public_key } = await getVapidPublicKey();
    available = Boolean(public_key);
  } catch {
    available = false;
  }
  let subscribed = false;
  try {
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    subscribed = Boolean(sub);
  } catch {
    subscribed = false;
  }
  return { supported: true, available, permission: Notification.permission, subscribed };
}

/**
 * Ask for permission, subscribe via the PushManager, and register the
 * subscription with the backend. Returns true on success. Throws an Error
 * with `.code === 'denied'` if the user blocked notifications.
 */
export async function enablePush() {
  if (!isPushSupported()) return false;

  const permission = await Notification.requestPermission();
  if (permission !== 'granted') {
    const err = new Error('Notifications are blocked. Enable them in your browser settings.');
    // @ts-ignore — custom discriminator for the caller
    err.code = 'denied';
    throw err;
  }

  const { public_key } = await getVapidPublicKey();
  if (!public_key) return false; // push not configured server-side

  const reg = await navigator.serviceWorker.ready;
  let sub = await reg.pushManager.getSubscription();
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key)
    });
  }

  const json = sub.toJSON();
  await subscribePush({ endpoint: sub.endpoint, keys: json.keys });
  return true;
}

/** Unsubscribe this device and tell the backend to forget it. */
export async function disablePush() {
  if (!isPushSupported()) return;
  const reg = await navigator.serviceWorker.ready;
  const sub = await reg.pushManager.getSubscription();
  if (!sub) return;
  try {
    await unsubscribePush(sub.endpoint);
  } finally {
    await sub.unsubscribe().catch(() => {});
  }
}
