// Merge the Deepline (HarvestAPI) LinkedIn profile with the Prospeo person match.
// LinkedIn is the source of truth for the current role; Prospeo supplies email, mobile and
// firmographics. When Prospeo's company is not the current employer, flag a company lookup.
const lead = $('Mark enriching').first().json;
const dl = $('Deepline: LinkedIn profile').first().json;
const pr = $('Prospeo: enrich person').first().json;

const str = (v) => (v === undefined || v === null || typeof v === 'object' || String(v).trim() === '' ? null : String(v).trim());
const slugOf = (url) => {
  const m = String(url || '').match(/linkedin\.com\/company\/([^\/?#]+)/i);
  return m ? m[1].toLowerCase() : null;
};

const profile = (dl && dl.result && dl.result.data && dl.result.data.element) || {};
const current = (Array.isArray(profile.currentPosition) && profile.currentPosition[0]) || {};
const prPerson = (pr && pr.error === false && pr.person) || {};
const prCompany = (pr && pr.error === false && pr.company) || {};

const loc = profile.location || {};
const currentCompanyUrl = str(current.companyLinkedinUrl);
const prospeoCompanyMatches = Boolean(
  prCompany.linkedin_url && currentCompanyUrl && slugOf(prCompany.linkedin_url) === slugOf(currentCompanyUrl),
) || (!currentCompanyUrl && Boolean(prCompany.name));

const email = prPerson.email || {};
const mobile = prPerson.mobile || {};
const emailStatus = email.email
  ? (String(email.status || '').toUpperCase() === 'VERIFIED' ? 'valid' : String(email.status || 'unknown').toLowerCase())
  : 'not_found';

return [{ json: {
  lead_id: lead.id,
  linkedin_url: lead.linkedin_url,
  first_name: str(profile.firstName) || str(prPerson.first_name),
  last_name: str(prPerson.last_name) || str(profile.lastName),
  full_name: str(prPerson.full_name) || [profile.firstName, profile.lastName].filter(Boolean).join(' ') || null,
  title: str(current.position) || str(prPerson.current_job_title),
  headline: str(profile.headline) || str(prPerson.headline),
  location: str(loc.linkedinText) || [prPerson.location && prPerson.location.city, prPerson.location && prPerson.location.country].filter(Boolean).join(', ') || null,
  about: str(profile.about),
  linkedin_followers: profile.followerCount ?? null,
  linkedin_connections: profile.connectionsCount ?? null,
  company_name: str(current.companyName) || str(prCompany.name),
  company_linkedin_url: currentCompanyUrl || str(prCompany.linkedin_url),
  work_email: str(email.email),
  email_status: emailStatus,
  phone: str(mobile.mobile),
  phone_type: str(mobile.mobile) ? 'mobile' : null,
  company: prospeoCompanyMatches ? prCompany : null,
  needs_company: !prospeoCompanyMatches && Boolean(currentCompanyUrl),
  sources: {
    deepline_job: dl && dl.job_id,
    prospeo_match: pr && pr.error === false,
    prospeo_error: pr && pr.error ? (pr.error_code || 'error') : null,
  },
} }];
