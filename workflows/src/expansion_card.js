// One expansion card per run: suggested colleagues ranked by fit, with Add as lead / Skip.
// Re-rendered (chat.update) after every Add/Skip so decided people lose their buttons.
const run = $input.first().json;
const people = Array.isArray(run.people) ? run.people : [];
const company = run.company_name || run.company_domain || 'this company';
const MAX_PEOPLE = 8;
const cut = (s, n) => (s && s.length > n ? s.slice(0, n - 1) + '…' : s);

const blocks = [];
if (people.length === 0) {
  blocks.push({ type: 'section', text: { type: 'mrkdwn', text: `:mag: No other matching people found at *${company}*.` } });
} else {
  blocks.push({ type: 'header', text: { type: 'plain_text', text: cut(`Found ${people.length} more people at ${company}`, 150) } });
  blocks.push({ type: 'context', elements: [{ type: 'mrkdwn', text: 'Ranked by persona fit. Nobody is contacted until you add and call them.' }] });
  for (const p of people.slice(0, MAX_PEOPLE)) {
    const email = p.work_email && ['valid', 'deliverable', 'verified'].includes(String(p.email_status).toLowerCase())
      ? ':white_check_mark: valid email' : ':x: no valid email';
    const score = p.fit_score ? `fit ${p.fit_score}/5` : 'fit n/a';
    blocks.push({ type: 'divider' });
    blocks.push({ type: 'section', text: { type: 'mrkdwn', text: cut(
      `*<${p.linkedin_url}|${p.full_name || p.linkedin_url}>* · ${p.title || 'title unknown'}\n${score} · ${email}\n_${p.fit_reason || 'No reason given'}_`, 2900) } });
    if (p.status === 'suggested') {
      blocks.push({ type: 'actions', elements: [
        { type: 'button', action_id: 'add_suggested_lead', style: 'primary', text: { type: 'plain_text', text: 'Add as lead' }, value: p.id },
        { type: 'button', action_id: 'skip_suggested_lead', text: { type: 'plain_text', text: 'Skip' }, value: p.id },
      ] });
    } else {
      const label = p.status === 'skipped' ? ':heavy_minus_sign: Skipped' : `:arrow_right: Added as lead (\`${p.status}\`)`;
      blocks.push({ type: 'context', elements: [{ type: 'mrkdwn', text: label }] });
    }
  }
}

const payload = { channel: run.slack_channel_id, text: `Account expansion: ${company}`, blocks, unfurl_links: false };
if (run.slack_message_ts) payload.ts = run.slack_message_ts;
else payload.thread_ts = run.slack_thread_ts;

return [{ json: {
  run_id: run.id,
  people_count: people.length,
  method: run.slack_message_ts ? 'chat.update' : 'chat.postMessage',
  payload,
} }];
