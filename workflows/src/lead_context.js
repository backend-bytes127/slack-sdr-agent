// Email waterfall result. Prospeo (from the person match) wins; otherwise the first valid email from
// Datagma, then Hunter (both via Deepline), otherwise the best unverified guess.
const base = $('Company context').first().json;

const fromDeepline = (node, source) => {
  if (!$(node).isExecuted) return null;
  const data = ((($(node).first().json || {}).result) || {}).data || {};
  if (!data.email) return null;
  const status = String(data.status || (data.verification && data.verification.status) || 'unknown').toLowerCase();
  return { email: String(data.email).toLowerCase(), status, source };
};

if (base.work_email) {
  return [{ json: { ...base, email_source: 'prospeo' } }];
}

const found = [fromDeepline('Deepline: Datagma email', 'datagma'), fromDeepline('Deepline: Hunter email', 'hunter')]
  .filter(Boolean);
const best = found.find((f) => f.status === 'valid') || found[0];
if (!best) {
  return [{ json: { ...base, email_source: null } }];
}
return [{ json: { ...base, work_email: best.email, email_status: best.status, email_source: best.source } }];
