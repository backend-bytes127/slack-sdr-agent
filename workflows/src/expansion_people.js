// One WF5 "person" callback per suggested colleague, with the Datagma email result (same shape the
// Clay Table 2 child rows posted). Items line up 1:1 with "Split people".
const { run_id } = $('Pick top people').first().json;
const people = $('Split people').all();

return $input.all().map((item, i) => {
  const data = ((item.json || {}).result || {}).data || {};
  const email = data.email
    ? { work_email: String(data.email).toLowerCase(), email_status: String(data.status || 'unknown').toLowerCase() }
    : { work_email: null, email_status: 'not_found' };
  return { json: { type: 'person', run_id, ...people[i].json, ...email } };
});
