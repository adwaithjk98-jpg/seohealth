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
 *   amount: string,
 *   cadence: string,
 *   tagline: string,
 *   features: string[],
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
    amount: '₹0',
    cadence: 'free forever',
    tagline: 'See exactly where your business stands online.',
    features: ['1 business', 'Monthly health check', 'Plain-English recommendations'],
    businesses: 1,
    auditsPerWeek: 1,
    competitors: 0,
    discoveryScansPerMonth: 0
  },
  paid: {
    key: 'paid',
    name: 'Pro',
    price: '₹549/mo',
    amount: '₹549',
    cadence: '/month',
    tagline: 'Everything you need to grow your local presence.',
    features: [
      'Weekly auto-audits',
      'Competitor discovery & tracking',
      'Monday digest when your score moves',
      'Step-by-step guided fixes'
    ],
    businesses: 1,
    auditsPerWeek: 7,
    competitors: 4,
    discoveryScansPerMonth: 1
  },
  max: {
    key: 'max',
    name: 'Max',
    price: '₹2,500/mo',
    amount: '₹2,500',
    cadence: '/month',
    tagline: 'Breadth for multi-location owners and agencies.',
    features: [
      'Everything in Pro',
      'Up to 10 businesses',
      '8 competitors tracked',
      '4 discovery scans / month',
      'Per-business weekly digest'
    ],
    businesses: 10,
    auditsPerWeek: 25,
    competitors: 8,
    discoveryScansPerMonth: 4
  }
};

/** Tier keys in display order (Free → Pro → Max). */
export const TIER_ORDER = /** @type {const} */ (['free', 'paid', 'max']);

/** Pro tier — the Free → Pro growth target. */
export const PRO = TIERS.paid;

/** Max tier — multi-location / agency. Only surfaced at a hit capacity limit. */
export const MAX = TIERS.max;
