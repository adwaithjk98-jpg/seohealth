// Shared motion helpers. CSS animations are already gated for reduced motion in
// app.css, but svelte/transition (JS) isn't — so we gate it here, in one place,
// to honor prefers-reduced-motion across the app.

import { browser } from '$app/environment';

/** True when the user has asked the OS to reduce motion. */
export function prefersReducedMotion() {
  return browser && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Wrap svelte/transition params so they collapse to an instant change when
 * reduced motion is requested. Spread into in:/out:/transition:.
 *
 *   import { fly } from 'svelte/transition';
 *   import { reduced } from '$lib/motion.js';
 *   <div in:fly={reduced({ y: 6, duration: 220 })}>
 *
 * @template {{ duration?: number, delay?: number }} T
 * @param {T} params
 * @returns {T}
 */
export function reduced(params) {
  if (prefersReducedMotion()) {
    return { ...params, duration: 0, delay: 0 };
  }
  return params;
}
