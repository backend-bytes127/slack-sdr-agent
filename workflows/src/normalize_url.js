// Accept only personal profile URLs (linkedin.com/in/<slug>), strip tracking params and
// trailing slashes, lowercase, and rebuild as https://www.linkedin.com/in/<slug>.
const body = $('Verify Slack signature').first().json.body || {};
const text = String(body.text || '').trim().replace(/^<|>$/g, '').split('|')[0];

const match = text.match(/linkedin\.com\/(?:mwlite\/)?in\/([^\/?#\s]+)/i);
let slug = null;
if (match) {
  try { slug = decodeURIComponent(match[1]).toLowerCase(); } catch (e) { slug = match[1].toLowerCase(); }
}

const base = {
  user_id: body.user_id || null,
  channel_id: body.channel_id || null,
  response_url: body.response_url || null,
  raw_text: text,
};

if (!slug) {
  const hint = /linkedin\.com\/(company|sales|school|pub)\//i.test(text)
    ? 'That looks like a company, school or Sales Navigator link.'
    : 'I could not find a LinkedIn profile URL in that.';
  return [{ json: { ...base, ok: false,
    error: `${hint} Use a personal profile URL like https://www.linkedin.com/in/jane-doe` } }];
}

return [{ json: { ...base, ok: true, linkedin_url: `https://www.linkedin.com/in/${slug}` } }];
