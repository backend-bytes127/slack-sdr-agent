// Normalise the Clay Table 1 callback into the leads columns.
// Clay sends whole enrichment objects (person, company, email_status) plus flat values; it may
// send numbers as strings and objects as JSON strings, so coerce everything defensively.
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const raw = $input.first().json.body || {};

const str =(v) => (v === undefined || v === null || typeof v === 'object' || String(v).trim() === '' ? null : String(v).trim());
const int = (v) => {
  const n = parseInt(String(v ?? '').replace(/[^0-9]/g, ''), 10);
  return Number.isFinite(n) ? n : null;
};
const parseMaybeJson = (v) => {
  if (v && typeof v === 'object') return v;
  if (typeof v !== 'string') return null;
  try { return JSON.parse(v.replace(/^```(json)?|```$/g, '').trim()); } catch (e) { return null; }
};
// First non-empty value among candidate keys, searched in each object in order
const pick = (objs, keys) => {
  for (const o of objs) {
    if (!o || typeof o !== 'object') continue;
    for (const k of keys) {
      const v = k.split('.').reduce((acc, part) => (acc == null ? acc : acc[part]), o);
      if (v !== undefined && v !== null && v !== '' && typeof v !== 'object') return v;
    }
  }
  return null;
};
const asLines = (v) => {
  if (Array.isArray(v)) return v.map((x) => `• ${String(x).replace(/^[-•*]\s*/, '')}`).join('\n');
  return str(v);
};
const domain = (v) => {
  const s = str(v);
  return s ? s.toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0] : null;
};

// Clay sends { lead_id, payload } where payload is the n8n_payload formula (object or JSON string)
const packed = parseMaybeJson(raw.payload);
const b = packed ? { ...packed, lead_id: raw.lead_id } : raw;

if (!UUID.test(String(str(b.lead_id) || ''))) {
  throw new Error(`Clay callback without a valid lead_id: ${JSON.stringify(b).slice(0, 300)}`);
}

const person = parseMaybeJson(b.person) || {};
const companyRaw = parseMaybeJson(b.company) || {};
// Current job: Clay's latest_experience, else the first current entry in experience[]
const currentJob = (person.latest_experience && typeof person.latest_experience === 'object')
  ? person.latest_experience
  : ((Array.isArray(person.experience) ? person.experience : []).find((e) => e && e.is_current) || {});
const jobDomain = domain(pick([currentJob, b], ['company_domain', 'domain']));
// Only trust firmographics that describe the current employer (Clay can match a board seat instead)
const companyDomain = domain(pick([companyRaw], ['companyWebsite', 'domain', 'website']));
const company = !jobDomain || !companyDomain || companyDomain === jobDomain ? companyRaw : {};
const P = [person, currentJob, b];

const research = parseMaybeJson(b.research) || {};
const emailObj = parseMaybeJson(b.email_status);
const emailStatusRaw = emailObj
  ? pick([emailObj, emailObj.results], ['status', 'result', 'results.status', 'message', 'email_status'])
  : str(b.email_status);
const workEmail = str(b.work_email) ? str(b.work_email).toLowerCase() : null;

const firstName = str(pick(P, ['first_name', 'firstName']));
const lastName = str(pick(P, ['last_name', 'lastName']));
const talking = research.talking_points || research.talkingPoints;

return [{ json: {
  lead_id: str(b.lead_id),
  first_name: firstName,
  last_name: lastName,
  full_name: str(pick(P, ['name', 'full_name', 'fullName'])) || [firstName, lastName].filter(Boolean).join(' ') || null,
  title: str(pick(P, ['title', 'job_title', 'jobTitle', 'latest_experience.title'])),
  headline: str(pick(P, ['headline'])),
  location: str(pick(P, ['location_name', 'location', 'locality'])),
  about: str(pick(P, ['summary', 'about'])),
  company_name: str(pick([person, currentJob, company, b], ['org', 'company', 'companyName', 'company_name'])),
  company_domain: jobDomain || companyDomain,
  company_linkedin_url: str(pick([currentJob, company, b], ['url', 'companyLinkedinUrl', 'company_linkedin_url'])),
  company_size: str(pick([company, b], ['companySize', 'size', 'employeeCount', 'company_size'])),
  industry: str(pick([company, b], ['industry', 'hubspotIndustry'])),
  company_description: str(pick([company, b], ['aboutUs', 'description', 'company_description'])),
  work_email: workEmail,
  email_status: workEmail ? (String(emailStatusRaw || 'unknown').toLowerCase()) : 'not_found',
  phone: str(b.phone),
  phone_type: str(b.phone_type) || (str(b.phone) ? 'mobile' : null),
  linkedin_followers: int(pick(P, ['num_followers', 'followers', 'follower_count', 'linkedin_followers'])),
  linkedin_connections: int(pick(P, ['connections', 'num_connections', 'connection_count', 'linkedin_connections'])),
  research_summary: asLines(research.summary) || (Object.keys(research).length ? null : str(b.research)),
  talking_points: asLines(talking) || str(b.talking_points),
  icp_fit: str(b.icp_fit),
  enrichment: b,
} }];
