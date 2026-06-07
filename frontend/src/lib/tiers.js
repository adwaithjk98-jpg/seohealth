// Tier display metadata for the upgrade / upsell surfaces.
//
// ENFORCEMENT source of truth is the backend (`app/services/subscriptions.py`
// TIER_LIMITS). These values mirror it *purely for marketing copy* so the
// conversion surfaces never scatter hardcoded numbers (a stale "3 competitors"
// in a nudge is a lie to the user). If the backend limits change, update here.

/**
 * @typedef {{
 *   key: 'free' | 'paid' | 'max',
 *   name: string,
 *   price: string,
 *   businesses: number,
 *   auditsPerWeek: number,
 *   competitors: number,
 *   discoveryScansPerMonth: number
 * }} TierMeta
 */

/** @type {Record<'free' | 'paid' | 'max', TierMeta>} */
export const TIERS = {
  free: {
    key: 'free',
    name: 'Free',
    price: '₹0',
    businesses: 1,
    auditsPerWeek: 1,
    competitors: 0,
    discoveryScansPerMonth: 0
  },
  paid: {
    key: 'paid',
    name: 'Pro',
    price: '₹549/mo',
    businesses: 1,
    auditsPerWeek: 7,
    competitors: 4,
    discoveryScansPerMonth: 1
  },
  max: {
    key: 'max',
    name: 'Max',
    price: '₹2,500/mo',
    businesses: 10,
    auditsPerWeek: 25,
    competitors: 8,
    discoveryScansPerMonth: 4
  }
};

/** Pro tier — the Free → Pro growth target. */
export const PRO = TIERS.paid;

/** Max tier — multi-location / agency. Only surfaced at a hit capacity limit. */
export const MAX = TIERS.max;
