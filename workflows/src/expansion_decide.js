// After the start-expansion SQL: either search the account for a new run, or explain why not.
const row = $input.first().json;
const company = row.company_name || row.company_domain || 'this company';
const permalink = (channel, ts) => (channel && ts ? `https://slack.com/archives/${channel}/p${String(ts).replace('.', '')}` : null);

if (row.new_run) {
  return [{ json: { start: true, run: row.new_run, lead: row } }];
}

let text;
if (!row.company_domain && !row.company_linkedin_url) {
  text = `:mag: Can't search for colleagues: no company was found for ${row.full_name || 'this lead'}.`;
} else if (row.recent_run) {
  const when = new Date(row.recent_run.created_at).toISOString().slice(0, 10);
  const link = permalink(row.recent_run.rc, row.recent_run.rt);
  text = `:mag: Already searched *${company}* on ${when}${link ? ` (<${link}|see that thread>)` : ''}. No new search spend.`;
} else {
  text = `:mag: Could not start the colleague search for ${company}.`;
}

return [{ json: { start: false, payload: { channel: row.slack_channel_id, thread_ts: row.slack_thread_ts, text } } }];
