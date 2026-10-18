// Rank candidates by the LLM persona-fit score and keep the best 8 with fit >= 3 (Clay Table 2 used limit 8).
// If the LLM answer can't be parsed, keep the first 8 unscored rather than dropping everyone.
const MAX_PEOPLE = 8;
const MIN_SCORE = 3;
const { run } = $('Decide').first().json;
const { candidates } = $('Candidates').first().json;

let scores = [];
if ($('Fit (LLM)').isExecuted) {
  try {
    scores = JSON.parse(String($('Fit (LLM)').first().json.text || '').replace(/^```(json)?|```$/g, '').trim());
  } catch (e) {
    scores = [];
  }
}
if (!Array.isArray(scores)) scores = [];
const byIndex = new Map(scores.map((s) => [Number(s.i), s]));

const people = candidates
  .map((c, i) => {
    const s = byIndex.get(i) || {};
    const score = Number(s.score) || null;
    return { ...c, fit: { score, reason: s.reason || null } };
  })
  .filter((c) => !scores.length || (c.fit.score || 0) >= MIN_SCORE)
  .sort((a, b) => (b.fit.score || 0) - (a.fit.score || 0))
  .slice(0, MAX_PEOPLE);

return [{ json: { run_id: run.id, expected_total: people.length, people } }];
