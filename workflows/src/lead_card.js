// Build the Block Kit lead card from the lead row. Buttons show only while the lead is
// waiting for a call; afterwards the `note` (or the status) replaces them.
const input = $('Called by parent').first().json;
const lead = $input.first().json;
const note = input.note || '';

const show = (v, fallback = '—') => (v === null || v === undefined || v === '' ? fallback : String(v));
const num = (v) => (v === null || v === undefined ? '—' : Number(v).toLocaleString('en-US'));
const cut = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s);

const emailLine = lead.work_email ? `${lead.work_email} (${show(lead.email_status, 'unknown')})` : 'No email found';
const phoneLine = lead.phone ? `${lead.phone}${lead.phone_type ? ` (${lead.phone_type})` : ''}` : 'No phone found, start on LinkedIn';
const portal = $env.HUBSPOT_PORTAL_ID;
const hubspotUrl = lead.hubspot_contact_id && portal
  ? `https://app.hubspot.com/contacts/${portal}/record/0-1/${lead.hubspot_contact_id}` : null;

const links = [`<${lead.linkedin_url}|LinkedIn>`];
if (hubspotUrl) links.push(`<${hubspotUrl}|HubSpot>`);
if (lead.source === 'account_expansion') links.push('_Suggested colleague_');

const blocks = [
  { type: 'header', text: { type: 'plain_text', text: cut(show(lead.full_name, 'Unknown name'), 150) } },
  { type: 'section', text: { type: 'mrkdwn', text: cut(`*${show(lead.title, 'Title unknown')}* at *${show(lead.company_name, 'company unknown')}*\n${show(lead.headline, '')}`, 2900) } },
  { type: 'section', fields: [
    { type: 'mrkdwn', text: `*Email*\n${emailLine}` },
    { type: 'mrkdwn', text: `*Phone*\n${phoneLine}` },
    { type: 'mrkdwn', text: `*Followers / Connections*\n${num(lead.linkedin_followers)} / ${num(lead.linkedin_connections)}` },
    { type: 'mrkdwn', text: `*Location*\n${show(lead.location)}` },
    { type: 'mrkdwn', text: `*Company*\n${show(lead.company_size)} · ${show(lead.industry)}` },
    { type: 'mrkdwn', text: `*ICP fit*\n${show(lead.icp_fit)}` },
  ] },
  { type: 'section', text: { type: 'mrkdwn', text: cut(`*Research*\n${show(lead.research_summary, '_No research returned_')}`, 2900) } },
  { type: 'section', text: { type: 'mrkdwn', text: cut(`*Talking points*\n${show(lead.talking_points, '_None_')}`, 2900) } },
  { type: 'context', elements: [{ type: 'mrkdwn', text: `${links.join('  ·  ')}  ·  status: \`${lead.status}\`` }] },
];

const awaitingCall = ['in_crm', 'enriched'].includes(lead.status) && !note;
if (awaitingCall) {
  blocks.push({ type: 'actions', elements: [
    { type: 'button', action_id: 'call_connected', style: 'primary', text: { type: 'plain_text', text: 'Picked up' }, value: lead.id },
    { type: 'button', action_id: 'call_no_answer', text: { type: 'plain_text', text: 'No answer' }, value: lead.id },
    { type: 'button', action_id: 'wrong_person', style: 'danger', text: { type: 'plain_text', text: 'Wrong person' }, value: lead.id },
  ] });
} else if (note) {
  blocks.push({ type: 'section', text: { type: 'mrkdwn', text: cut(note, 2900) } });
}

const useUpdate = input.mode === 'update' && lead.card_message_ts;
const payload = {
  channel: lead.slack_channel_id,
  text: `Lead card: ${show(lead.full_name, lead.linkedin_url)}`,
  blocks,
  unfurl_links: false,
};
if (useUpdate) payload.ts = lead.card_message_ts;
else payload.thread_ts = lead.slack_thread_ts;

return [{ json: { lead_id: lead.id, method: useUpdate ? 'chat.update' : 'chat.postMessage', payload } }];
