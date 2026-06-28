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
    features: ['1 business', 'Up to 2 audits a week', 'Plain-English recommendations'],
    businesses: 1,
    auditsPerWeek: 2,
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
    price: '₹1,999/mo',
    amount: '₹1,999',
    cadence: '/month',
    tagline: 'Everything in Pro, turned up — deeper insight, faster audits, more eyes on the competition. Built to scale with you.',
    features: [
      'Everything in Pro, supercharged',
      'Audits & competitor refresh twice as often',
      '8 competitors tracked per business',
      '4 discovery scans / month',
      'Run up to 5 businesses or locations'
    ],
    businesses: 5,
    auditsPerWeek: 20,
    competitors: 8,
    discoveryScansPerMonth: 4
  }
};

/** Tier keys in display order (Free → Pro → Max). */
export const TIER_ORDER = /** @type {const} */ (['free', 'paid', 'max']);

/** Pro tier — the Free → Pro growth target. */
export const PRO = TIERS.paid;

/** Max tier — the Pro power-up (also fits multi-location). Surfaced at a hit capacity limit. */
export const MAX = TIERS.max;
