// Verify the Slack request signature: HMAC-SHA256("v0:" + ts + ":" + rawBody) with the signing secret.
// Rejects requests older than 5 minutes. Outputs { valid, reason, body }.
const crypto = require('crypto');

const MAX_AGE_SECONDS = 300;
const item = $input.first();
const headers = item.json.headers || {};
const ts = headers['x-slack-request-timestamp'];
const signature = headers['x-slack-signature'];
const secret = $env.SLACK_SIGNING_SECRET;

const fail = (reason) => [{ json: { valid: false, reason, body: item.json.body } }];

if (!secret) return fail('SLACK_SIGNING_SECRET is not set');
if (!ts || !signature) return fail('missing Slack signature headers');
if (Math.abs(Date.now() / 1000 - Number(ts)) > MAX_AGE_SECONDS) return fail('stale request');

let raw = '';
if (item.binary && item.binary.data) {
  raw = (await this.helpers.getBinaryDataBuffer(0, 'data')).toString('utf8');
}

const expected = 'v0=' + crypto.createHmac('sha256', secret).update(`v0:${ts}:${raw}`).digest('hex');
const valid = expected.length === signature.length &&
  crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(signature));

return valid ? [{ json: { valid: true, body: item.json.body } }] : fail('bad signature');
