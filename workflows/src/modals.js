// Build the views.open payload for the call-notes modal or the edit-draft modal.
// Runs right after parsing so the 3-second trigger_id window is respected.
const item = $input.first().json;
const action = $('Parse Slack payload').first().json;
const opt = (text, value) => ({ text: { type: 'plain_text', text }, value });

const meta = JSON.stringify({
  lead_id: action.lead_id,
  channel: action.channel,
  message_ts: action.message_ts,
});

let view;
if (action.action === 'call_connected') {
  view = {
    type: 'modal',
    callback_id: 'call_notes_submit',
    private_metadata: meta,
    title: { type: 'plain_text', text: 'Call notes' },
    submit: { type: 'plain_text', text: 'Save & draft' },
    close: { type: 'plain_text', text: 'Cancel' },
    blocks: [
      { type: 'input', block_id: 'result', label: { type: 'plain_text', text: 'Call outcome' },
        element: { type: 'static_select', action_id: 'call_result', initial_option: opt('Interested, follow up', 'interested'),
          options: [opt('Meeting booked', 'meeting_booked'), opt('Interested, follow up', 'interested'),
            opt('Not now', 'not_now'), opt('Not interested', 'not_interested')] } },
      { type: 'input', block_id: 'notes', label: { type: 'plain_text', text: 'Call notes' },
        element: { type: 'plain_text_input', action_id: 'call_notes', multiline: true,
          placeholder: { type: 'plain_text', text: 'What did they say? Pains, timing, next step…' } } },
      { type: 'input', block_id: 'goal', label: { type: 'plain_text', text: 'Message goal' },
        element: { type: 'static_select', action_id: 'message_goal', initial_option: opt('Recap and meeting confirmation', 'recap_and_meeting_confirmation'),
          options: [opt('Recap and meeting confirmation', 'recap_and_meeting_confirmation'),
            opt('Share a resource', 'share_a_resource'), opt('Soft follow-up', 'soft_follow_up')] } },
    ],
  };
} else {
  view = {
    type: 'modal',
    callback_id: 'edit_message_submit',
    private_metadata: meta,
    title: { type: 'plain_text', text: 'Edit message' },
    submit: { type: 'plain_text', text: 'Save draft' },
    close: { type: 'plain_text', text: 'Cancel' },
    blocks: [
      { type: 'input', block_id: 'draft', label: { type: 'plain_text', text: 'LinkedIn message' },
        element: { type: 'plain_text_input', action_id: 'draft_text', multiline: true, max_length: 3000,
          initial_value: String(item.draft || '') } },
    ],
  };
}

return [{ json: { payload: { trigger_id: action.trigger_id, view } } }];
