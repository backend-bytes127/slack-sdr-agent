// Slack returns HTTP 200 with ok:false on errors, so fail loudly here.
const res = $input.first().json;
const input = $('Called by parent').first().json;
if (!res.ok) {
  const detail = res.response_metadata && res.response_metadata.messages
    ? ` (${res.response_metadata.messages.join('; ')})` : '';
  throw new Error(`Slack ${input.method} failed: ${res.error}${detail}`);
}
return [{ json: res }];
