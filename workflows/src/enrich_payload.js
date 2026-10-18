// Build the WF2 callback payload (same shape Clay used to send) from the lead context
// (profile + Prospeo + company page + email waterfall) and the LLM research.
const m = $('Lead context').first().json;
const company = m.company || {};

const str = (v) => (v === undefined || v === null || typeof v === 'object' || String(v).trim() === '' ? null : String(v).trim());
let research = {};
try {
  research = JSON.parse(String($input.first().json.text || '').replace(/^```(json)?|```$/g, '').trim());
} catch (e) {
  research = { summary: [String($input.first().json.text || '').slice(0, 500)], talking_points: [] };
}

const SENIOR = /\b(vp|vice president|head|director|chief|c[eotfmr]o|founder|founding|co-founder|owner|partner|president)\b/i;
const size = Number(company.employee_count) || null;
const icpFit = SENIOR.test(m.title || '') && (!size || (size >= 11 && size <= 1000)) ? 'yes' : 'no';

return [{ json: {
  lead_id: m.lead_id,
  first_name: m.first_name,
  last_name: m.last_name,
  full_name: m.full_name,
  title: m.title,
  headline: m.headline,
  location: m.location,
  about: m.about,
  linkedin_followers: m.linkedin_followers,
  linkedin_connections: m.linkedin_connections,
  company_name: str(company.name) || m.company_name,
  company_domain: str(company.domain) || m.company_domain,
  company_linkedin_url: m.company_linkedin_url || str(company.linkedin_url),
  company_size: str(company.employee_range) || (size ? String(size) : null),
  industry: str(company.industry),
  company_description: str(company.description_ai) || str(company.description),
  work_email: m.work_email,
  email_status: m.email_status,
  phone: m.phone,
  phone_type: m.phone_type,
  research: { summary: research.summary || [], talking_points: research.talking_points || research.talkingPoints || [] },
  icp_fit: icpFit,
  enrichment_source: 'deepline+prospeo',
  sources: { ...m.sources, email: m.email_source },
} }];
