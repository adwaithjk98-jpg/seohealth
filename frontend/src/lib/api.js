// Tiny fetch wrappers for the dashboard. Keep it dependency-free.

async function readJsonError(res) {
  try {
    const data = await res.json();
    if (typeof data?.detail === 'string') return data.detail;
    if (Array.isArray(data?.detail) && data.detail[0]?.msg) return data.detail[0].msg;
    // Structured backend errors come back as
    //   {detail: {code, message, ...other-fields}}
    // e.g. the 402 competitor_limit_reached and 429 audit_weekly_limit
    // shapes. Surface the human-readable ``message`` rather than letting
    // the helper fall through to "Request failed (402)" which leaks the
    // raw HTTP status to the user.
    if (typeof data?.detail?.message === 'string') return data.detail.message;
  } catch {
    /* fall through */
  }
  return `Request failed (${res.status})`;
}

export async function getAudit(auditId) {
  const res = await fetch(`/api/audits/${auditId}`);
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

export async function getLatestAuditForBusiness(businessId) {
  const res = await fetch(`/api/businesses/${businessId}/latest-audit`);
  if (!res.ok) {
    const err = new Error(await readJsonError(res));
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function patchRecommendation(recId, fixStatus) {
  const res = await fetch(`/api/recommendations/${recId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ fix_status: fixStatus })
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

export async function startAudit(businessId) {
  const res = await fetch('/api/audits', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ business_id: businessId })
  });
  if (!res.ok) {
    const err = new Error(await readJsonError(res));
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function getAuditQuota() {
  const res = await fetch('/api/audits/quota', { credentials: 'same-origin' });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

// --- Competitors (Phase 4) --------------------------------------------------

export async function listCompetitors(businessId) {
  const res = await fetch(`/api/businesses/${businessId}/competitors`, {
    credentials: 'same-origin'
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

/**
 * @param {number} businessId
 * @param {{ maps_url: string, name?: string, instagram_url?: string, website_url?: string }} payload
 */
export async function addCompetitor(
  businessId,
  { maps_url, name, instagram_url, website_url }
) {
  const body = { maps_url };
  if (name) body.name = name;
  if (instagram_url) body.instagram_url = instagram_url;
  if (website_url) body.website_url = website_url;
  const res = await fetch(`/api/businesses/${businessId}/competitors`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    const err = new Error(await readJsonError(res));
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function deleteCompetitor(businessId, competitorId) {
  const res = await fetch(
    `/api/businesses/${businessId}/competitors/${competitorId}`,
    { method: 'DELETE', credentials: 'same-origin' }
  );
  if (!res.ok && res.status !== 204) throw new Error(await readJsonError(res));
}

/**
 * Soft-archive one of the user's own businesses. The row stays in the
 * DB (audit history + competitor observations survive) but drops out
 * of the dashboard and the per-plan business cap.
 * @param {number} businessId
 */
export async function archiveBusiness(businessId) {
  const res = await fetch(`/api/businesses/${businessId}`, {
    method: 'DELETE',
    credentials: 'same-origin'
  });
  if (!res.ok && res.status !== 204) throw new Error(await readJsonError(res));
}

/**
 * Fetch a single business by id. Mirrors the row shape used by the
 * dashboard's list endpoint so the detail page can read
 * `audit_schedule_cadence` / `next_auto_audit_at` without piggybacking
 * on the audit detail payload (which doesn't carry them).
 * @param {number} businessId
 */
export async function getBusiness(businessId) {
  const res = await fetch(`/api/businesses/${businessId}`, {
    credentials: 'same-origin'
  });
  if (!res.ok) {
    const err = new Error(await readJsonError(res));
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/**
 * Update FTUE questionnaire answers for a business. Pass only the
 * fields you want to write — null / undefined keep the existing value.
 * @param {number} businessId
 * @param {{
 *   business_type?: 'cafe' | 'salon' | 'retail' | 'service' | 'supplier' | 'other' | null,
 *   has_website?: boolean | null,
 *   has_instagram?: boolean | null
 * }} patch
 */
export async function updateBusinessProfile(businessId, patch) {
  const res = await fetch(`/api/businesses/${businessId}/profile`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(patch)
  });
  if (!res.ok) {
    const err = new Error(await readJsonError(res));
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/**
 * Set or clear the auto-audit cadence on a business. ``cadence=null``
 * turns scheduling off. Returns the updated business row.
 * @param {number} businessId
 * @param {'weekly' | 'biweekly' | 'monthly' | null} cadence
 */
export async function setBusinessSchedule(businessId, cadence) {
  const res = await fetch(`/api/businesses/${businessId}/schedule`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ cadence })
  });
  if (!res.ok) {
    const err = new Error(await readJsonError(res));
    err.status = res.status;
    throw err;
  }
  return res.json();
}

export async function getBusinessTrends(businessId) {
  const res = await fetch(`/api/businesses/${businessId}/trends`, {
    credentials: 'same-origin'
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

/** @param {number} businessId */
export async function getCompetitorInsights(businessId) {
  const res = await fetch(`/api/businesses/${businessId}/competitor-insights`, {
    credentials: 'same-origin'
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

// --- Discovery scan (Phase 4) -----------------------------------------------
// The scan is async: POST returns immediately with a `pending` row, and the
// caller polls GET until `status` is terminal (`done` or `failed`).

/**
 * @param {{ business_id: number, query: string, num_leads?: number, fields?: string[], filters?: string | null }} payload
 */
export async function createDiscoveryScan(payload) {
  const body = {
    business_id: payload.business_id,
    query: payload.query,
    num_leads: payload.num_leads ?? 20,
    fields:
      payload.fields ?? [
        'name',
        'address',
        'category',
        'rating',
        'review_count',
        'maps_url',
        // Pulling these so the discovery cards can show real IG /
        // website status (✓ / —) instead of "Checked after you Track",
        // and so the Competitor row gets ``instagram_url`` populated
        // at Track time — that's what the weekly refresh uses to
        // scrape follower/post counts going forward.
        'website',
        'instagram_url'
      ],
    filters: payload.filters ?? null
  };
  const res = await fetch('/api/discovery-scans', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(body)
  });
  if (!res.ok) {
    const err = new Error(await readJsonError(res));
    err.status = res.status;
    throw err;
  }
  return res.json();
}

/** @param {number} scanId */
export async function getDiscoveryScan(scanId) {
  const res = await fetch(`/api/discovery-scans/${scanId}`, {
    credentials: 'same-origin'
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

/**
 * List prior done scans for the caller. Optional business filter scopes
 * the result to one anchor business. Used by the Add-competitors gateway
 * to prefer revisiting an earlier list over burning a fresh scan.
 * @param {{ business_id?: number } | undefined} opts
 */
export async function listDiscoveryScans(opts) {
  const qs = opts?.business_id ? `?business_id=${opts.business_id}` : '';
  const res = await fetch(`/api/discovery-scans${qs}`, {
    credentials: 'same-origin'
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

// --- Subscriptions ----------------------------------------------------------

export async function getSubscriptionState() {
  const res = await fetch('/api/subscriptions/me', { credentials: 'same-origin' });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

export async function startSubscriptionCheckout(planTier = 'paid') {
  const res = await fetch('/api/subscriptions/checkout', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify({ plan_tier: planTier })
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

export async function cancelSubscription() {
  const res = await fetch('/api/subscriptions/cancel', {
    method: 'POST',
    credentials: 'same-origin'
  });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

export async function exportMyData() {
  const res = await fetch('/api/auth/me/export', { credentials: 'same-origin' });
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

export async function deleteMyAccount() {
  const res = await fetch('/api/auth/me', {
    method: 'DELETE',
    credentials: 'same-origin'
  });
  // 204 No Content is success but has no JSON body.
  if (!res.ok && res.status !== 204) throw new Error(await readJsonError(res));
  return true;
}

// Razorpay Checkout JS is only needed when real keys are configured. Load it
// on demand so dev/mock flows never pay the third-party request cost.
let _razorpayScriptPromise = null;

export function loadRazorpayCheckout() {
  if (typeof window === 'undefined') return Promise.resolve(false);
  if (window.Razorpay) return Promise.resolve(true);
  if (_razorpayScriptPromise) return _razorpayScriptPromise;
  _razorpayScriptPromise = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.async = true;
    script.onload = () => resolve(true);
    script.onerror = () => {
      _razorpayScriptPromise = null;
      reject(new Error('Could not load Razorpay checkout. Are you online?'));
    };
    document.head.appendChild(script);
  });
  return _razorpayScriptPromise;
}
