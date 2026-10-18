// Firmographics for the current employer: Prospeo's company when it matched the LinkedIn employer,
// otherwise the employer's LinkedIn company page (Deepline / HarvestAPI). The domain comes from its website.
const m = $('Merge profile + Prospeo').first().json;
const domainOf = (url) => {
  const host = String(url || '').trim().toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').split(/[\/?#]/)[0];
  return host.includes('.') ? host : null;
};

let company = m.company || {};
if ($('Deepline: LinkedIn company').isExecuted) {
  const res = $('Deepline: LinkedIn company').first().json || {};
  const el = (res.result && res.result.data && res.result.data.element) || null;
  if (el && el.name) {
    const range = el.employeeCountRange || {};
    company = {
      name: el.name,
      domain: domainOf(el.website),
      linkedin_url: el.linkedinUrl || null,
      employee_count: el.employeeCount ?? null,
      employee_range: range.start ? `${range.start}-${range.end || '+'}` : null,
      industry: ((el.industries || [])[0] || {}).name || null,
      description: el.description || el.tagline || null,
    };
  }
}

return [{ json: {
  ...m,
  company,
  company_name: company.name || m.company_name,
  company_domain: company.domain || domainOf(company.website) || null,
} }];
