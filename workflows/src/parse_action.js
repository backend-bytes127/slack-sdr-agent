// Parse a Slack interactivity payload (button click or modal submit) into one flat item.
// `route` is the Switch output index; unknown actions go to the last output.
const ROUTES = [
  'call_no_answer', 'call_connected', 'wrong_person', 'call_notes_submit',
  'send_message', 'edit_message', 'edit_message_submit', 'regenerate_message',
  'copy_message', 'add_suggested_lead', 'skip_suggested_lead', 'retry_lead',
];
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const body = $('Verify Slack signature').first().json.body || {};
let payload = {};
try { payload = JSON.parse(body.payload || '{}'); } catch (e) { payload = {}; }

const flattenState = (state) => {
  const out = {};
  for (const block of Object.values((state && state.values) || {})) {
    for (const [actionId, field] of Object.entries(block)) {
      out[actionId] = field.selected_option ? field.selected_option.value : (field.value ?? null);
    }
  }
  return out;
};

let action = 'unknown';
let leadId = null;
let meta = {};
let values = {};

if (payload.type === 'block_actions') {
  const first = (payload.actions || [])[0] || {};
  action = first.action_id || 'unknown';
  leadId = first.value || null;
} else if (payload.type === 'view_submission') {
  action = (payload.view && payload.view.callback_id) || 'unknown';
  try { meta = JSON.parse((payload.view && payload.view.private_metadata) || '{}'); } catch (e) { meta = {}; }
  leadId = meta.lead_id || null;
  values = flattenState(payload.view && payload.view.state);
}

const index = ROUTES.indexOf(action);
const user = payload.user || {};

return [{ json: {
  route: index === -1 || !UUID.test(String(leadId)) ? ROUTES.length : index,
  action,
  lead_id: UUID.test(String(leadId)) ? leadId : null,
  user_id: user.id || null,
  user_name: user.name || user.username || null,
  trigger_id: payload.trigger_id || null,
  channel: (payload.channel && payload.channel.id) || (payload.container && payload.container.channel_id) || meta.channel || null,
  message_ts: (payload.container && payload.container.message_ts) || meta.message_ts || null,
  values,
  meta,
} }];
