// Tiny fetch wrappers for the dashboard. Keep it dependency-free.

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

export async function getAudit(auditId) {
  const res = await fetch(`/api/audits/${auditId}`);
  if (!res.ok) throw new Error(await readJsonError(res));
  return res.json();
}

export async function getLatestAuditForBusiness(businessId) {
  const res = await fetch(`/api/businesses/${businessId}/latest-audit`);
  if (!res.ok) throw new Error(await readJsonError(res));
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

export async function addCompetitor(businessId, { maps_url, name }) {
  const body = { maps_url };
  if (name) body.name = name;
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

export async function getBusinessTrends(businessId) {
  const res = await fetch(`/api/businesses/${businessId}/trends`, {
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
