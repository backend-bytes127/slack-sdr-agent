// People at the lead's account: Prospeo search (decision-maker seniorities), or LinkedIn employees via
// Deepline/HarvestAPI when Prospeo has nobody. Drops the original lead, persona exclusions and duplicates.
const { lead } = $('Decide').first().json;
const MAX_CANDIDATES = 20;
const EXCLUDE = /\b(intern|recruit\w*|talent|human resources|hr|student|assistant|trainee)\b/i;

const slugOf = (url) => {
  const m = String(url || '').match(/linkedin\.com\/in\/([^\/?#\s]+)/i);
  if (!m) return null;
  try { return decodeURIComponent(m[1]).toLowerCase(); } catch (e) { return m[1].toLowerCase(); }
};
const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '');

let people = [];
let source = null;
const search = $('Prospeo: search people').first().json || {};
if (Array.isArray(search.results) && search.results.length) {
  source = 'prospeo';
  people = search.results.map(({ person = {} }) => {
    const loc = person.location || {};
    return {
      linkedin_url: person.linkedin_url,
      first_name: person.first_name,
      last_name: person.last_name,
      full_name: person.full_name,
      title: person.current_job_title,
      headline: person.headline,
      location: [loc.city, loc.country].filter(Boolean).join(', ') || null,
    };
  });
} else if ($('Deepline: LinkedIn employees').isExecuted) {
  source = 'linkedin';
  const res = $('Deepline: LinkedIn employees').first().json || {};
  const elements = (res.result && res.result.data && res.result.data.elements) || [];
  // HarvestAPI matches currentCompanies by name, so keep only people whose current company is the lead's
  people = elements
    .map((e) => ({ e, pos: (e.currentPositions || [])[0] || {} }))
    .filter(({ pos }) => !lead.company_name || norm(pos.companyName) === norm(lead.company_name))
    .map(({ e, pos }) => ({
      linkedin_url: e.linkedinUrl,
      first_name: e.firstName,
      last_name: e.lastName,
      full_name: [e.firstName, e.lastName].filter(Boolean).join(' ').trim() || null,
      title: pos.title || null,
      headline: e.headline || null,
      location: (e.location && e.location.linkedinText) || null,
    }));
}

const original = slugOf(lead.linkedin_url);
const seen = new Set();
const candidates = people.filter((p) => {
  const slug = slugOf(p.linkedin_url);
  if (!slug || slug === original || seen.has(slug)) return false;
  seen.add(slug);
  return !EXCLUDE.test(`${p.title || ''}`);
}).slice(0, MAX_CANDIDATES);

return [{ json: { source, candidates } }];
