// Build the "Something failed" Slack alert. Goes in the lead's thread (with Retry) when the
// lead is known, otherwise to the main channel.
const input = $('Called by parent').first().json;
const row = $input.first().json;
const cut = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s);

const text = `:warning: Something failed at *${input.step || 'unknown step'}* (${input.workflow || 'workflow'})\n` +
  '```' + cut(String(input.error || 'no error message'), 1500) + '```';

const blocks = [{ type: 'section', text: { type: 'mrkdwn', text } }];
if (row.id) {
  blocks.push({ type: 'actions', elements: [
    { type: 'button', action_id: 'retry_lead', style: 'primary', text: { type: 'plain_text', text: 'Retry' }, value: row.id },
  ] });
}

const payload = {
  channel: row.slack_channel_id || $env.SLACK_CHANNEL_ID,
  text: 'Something failed',
  blocks,
  unfurl_links: false,
  unfurl_media: false,
};
if (row.slack_thread_ts) payload.thread_ts = row.slack_thread_ts;

return [{ json: { payload } }];
