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
