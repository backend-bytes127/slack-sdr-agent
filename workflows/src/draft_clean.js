// Clean the LLM output: strip wrapping quotes/fences and whitespace. Never truncate silently;
// the draft card warns when it is over the LinkedIn note limit.
const input = $('Called by parent').first().json;
const raw = String($input.first().json.text || '').trim();
const draft = raw.replace(/^```[a-z]*\n?|```$/g, '').trim().replace(/^["“](.*)["”]$/s, '$1').trim();
if (!draft) throw new Error('LLM returned an empty draft');
return [{ json: { lead_id: input.lead_id, draft } }];
