// Render the AI draft message with Send / Edit / Regenerate / Copy buttons.
// Input item: { lead_id, draft, channel, thread_ts?, message_ts? } — message_ts means update in place.
const item = $input.first().json;
const MAX_LINKEDIN_NOTE = 300;
const draft = String(item.draft || '').trim();
const length = draft.length;
const lengthNote = length > MAX_LINKEDIN_NOTE
  ? `:warning: ${length} chars, over the ${MAX_LINKEDIN_NOTE}-char connection-note limit; edit before sending`
  : `${length}/${MAX_LINKEDIN_NOTE} chars`;

const blocks = [
  { type: 'section', text: { type: 'mrkdwn', text: '*AI draft LinkedIn message* (nothing is sent until you click Send)' } },
  { type: 'section', text: { type: 'mrkdwn', text: '>' + draft.replace(/\n/g, '\n>') } },
  { type: 'context', elements: [{ type: 'mrkdwn', text: lengthNote }] },
  { type: 'actions', elements: [
    { type: 'button', action_id: 'send_message', style: 'primary', text: { type: 'plain_text', text: 'Send via HeyReach' }, value: item.lead_id },
    { type: 'button', action_id: 'edit_message', text: { type: 'plain_text', text: 'Edit' }, value: item.lead_id },
    { type: 'button', action_id: 'regenerate_message', text: { type: 'plain_text', text: 'Regenerate' }, value: item.lead_id },
    { type: 'button', action_id: 'copy_message', text: { type: 'plain_text', text: "Copy, I'll send it" }, value: item.lead_id },
  ] },
];

const payload = { channel: item.channel, text: 'AI draft LinkedIn message', blocks };
if (item.message_ts) payload.ts = item.message_ts;
else payload.thread_ts = item.thread_ts;

return [{ json: { ...item, method: item.message_ts ? 'chat.update' : 'chat.postMessage', payload } }];
