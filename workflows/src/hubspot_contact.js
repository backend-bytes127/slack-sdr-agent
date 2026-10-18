// Decide create vs update for the HubSpot contact and build its properties.
// Never overwrites an existing owner; reports it so the SDR is warned instead.
const lead = $('Load lead').first().json;
const search = $('Search contact').first().json;
const existing = (search.results || [])[0] || null;

const props = {
  firstname: lead.first_name,
  lastname: lead.last_name,
  jobtitle: lead.title,
  company: lead.company_name,
  phone: lead.phone,
  city: lead.location,
  linkedin_url: lead.linkedin_url,
  linkedin_followers: lead.linkedin_followers,
  linkedin_connections: lead.linkedin_connections,
  research_summary: lead.research_summary,
};
if (lead.work_email) props.email = lead.work_email;

const existingOwner = existing && existing.properties ? existing.properties.hubspot_owner_id : null;
if (lead.hubspot_owner_id && !existingOwner) props.hubspot_owner_id = lead.hubspot_owner_id;

const clean = Object.fromEntries(Object.entries(props).filter(([, v]) => v !== null && v !== undefined && v !== ''));

return [{ json: {
  exists: Boolean(existing),
  contact_id: existing ? existing.id : null,
  owner_conflict: Boolean(existingOwner && lead.hubspot_owner_id && existingOwner !== lead.hubspot_owner_id),
  properties: clean,
} }];
