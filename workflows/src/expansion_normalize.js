// The expansion sub (or Clay Table 2) sends two kinds of callbacks to WF5:
//   { type: "expected_total", run_id, expected_total }      (parent row, once)
//   { type: "person", run_id, linkedin_url, ... }           (child rows, one per person)
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const b = $input.first().json.body || {};

const str = (v) => (v === undefined || v === null || String(v).trim() === '' ? null : String(v).trim());
const int = (v) => {
  const n = parseInt(String(v ?? '').replace(/[^0-9-]/g, ''), 10);
  return Number.isFinite(n) ? n : null;
};

if (!UUID.test(String(b.run_id || ''))) {
  throw new Error(`Expansion callback without a valid run_id: ${JSON.stringify(b).slice(0, 300)}`);
}

const isTotal = String(b.type || '').toLowerCase() === 'expected_total' ||
  (b.expected_total !== undefined && !b.linkedin_url);

if (isTotal) {
  return [{ json: { kind: 'total', run_id: b.run_id, expected_total: Math.max(0, int(b.expected_total) ?? 0) } }];
}

const match = String(b.linkedin_url || '').match(/linkedin\.com\/(?:mwlite\/)?in\/([^\/?#\s]+)/i);
let slug = null;
if (match) {
  try { slug = decodeURIComponent(match[1]); } catch (e) { slug = match[1]; }
  // Vanity slugs are case-insensitive; LinkedIn member IDs (ACw...) are not
  if (!/^ACw/.test(slug)) slug = slug.toLowerCase();
}

// AI fit column may return {"score":4,"reason":"..."} or separate fields
let fit = b.fit;
if (typeof fit === 'string') { try { fit = JSON.parse(fit); } catch (e) { fit = null; } }
fit = fit || {};

const firstName = str(b.first_name);
const lastName = str(b.last_name);

return [{ json: {
  kind: 'person',
  run_id: b.run_id,
  linkedin_url: slug ? `https://www.linkedin.com/in/${slug}` : null,
  first_name: firstName,
  last_name: lastName,
  full_name: str(b.full_name) || [firstName, lastName].filter(Boolean).join(' ') || null,
  title: str(b.title),
  headline: str(b.headline),
  location: str(b.location),
  linkedin_followers: int(b.linkedin_followers),
  linkedin_connections: int(b.linkedin_connections),
  work_email: str(b.work_email) ? str(b.work_email).toLowerCase() : null,
  email_status: str(b.work_email) ? ((str(b.email_status) || 'unknown').toLowerCase()) : 'not_found',
  fit_score: int(fit.score ?? b.fit_score),
  fit_reason: str(fit.reason ?? b.fit_reason),
  enrichment: b,
} }];
