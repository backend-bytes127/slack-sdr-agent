"""Account expansion sub-workflow: Prospeo people search (Deepline LinkedIn employees as fallback), LLM persona
fit, Datagma emails, then WF5 callbacks in the same shape Clay Table 2 used to post."""
from lib import Workflow, call, code, cred, http, if_true, slack, sql, sub_trigger

DEEPLINE_EXECUTE = "={{{{ ($env.DEEPLINE_API_BASE || 'https://code.deepline.com/api/v2') + '/integrations/{tool}/execute' }}}}"
PROSPEO = "($env.PROSPEO_API_BASE || 'https://api.prospeo.io')"
WF5_HOOK = "http://localhost:5678/webhook/sdr-expansion"
SENIORITIES = ["C-Suite", "Founder/Owner", "Vice President", "Director", "Head", "Partner"]

# A run starts when the lead has a company domain or company LinkedIn page and no run for that domain
# happened in the last 30 days (no repeat spend).
EXPANSION_START_SQL = """
with l as (select * from leads where id = $1::uuid),
recent as (
  select r.id, r.created_at, x.slack_channel_id as rc, x.slack_thread_ts as rt
  from expansion_runs r join leads x on x.id = r.lead_id, l
  where l.company_domain is not null and r.company_domain = l.company_domain
    and r.created_at > now() - interval '30 days' and r.status <> 'error'
  order by r.created_at desc limit 1
),
ins as (
  insert into expansion_runs (lead_id, company_domain, company_name, slack_channel_id, slack_thread_ts)
  select l.id, l.company_domain, l.company_name, l.slack_channel_id, l.slack_thread_ts from l
  where (l.company_domain is not null or l.company_linkedin_url is not null) and not exists (select 1 from recent)
  returning *
)
select l.*, (select row_to_json(recent) from recent) as recent_run,
       (select row_to_json(ins) from ins) as new_run
from l
""".strip()

FIT_PROMPT = """=Score how well each person fits this buyer persona. An SDR wants other people to call at the same account.

Persona: {{ $env.BUYER_PERSONA || 'senior decision makers in sales, growth or revenue' }}
Original lead: {{ $('Decide').first().json.lead.title }} at {{ $('Decide').first().json.lead.company_name }}

People (index. title | headline):
{{ $json.candidates.map((c, i) => i + '. ' + (c.title || 'n/a') + ' | ' + String(c.headline || '').slice(0, 120)).join('\\n') }}

Return JSON only, no markdown: [{"i": <index>, "score": <1-5>, "reason": "<one short line>"}] with one entry per person."""


def _post_wf5(wf, name, body_expr):
    return http(wf, name, "POST", WF5_HOOK, "claycb", body_expr=body_expr, retry=True)


def expansion_start():
    wf = Workflow("exp_start", "SDR · sub · Start account expansion (Prospeo search)")
    lead = "$('Decide').first().json.lead"
    t = sub_trigger(wf, ["lead_id"])
    s = sql(wf, "Create expansion run", EXPANSION_START_SQL, "[$json.lead_id ?? null]")
    d = code(wf, "Decide", "expansion_decide")
    go = if_true(wf, "New run?", "$json.start")
    skip = slack(wf, "Explain skip", "'chat.postMessage'", "$json.payload", pos=[wf._x, 250])
    search = http(wf, "Prospeo: search people", "POST", "={{ " + PROSPEO + " + '/search-person' }}", "prospeo",
                  body_expr=f"JSON.stringify({{ page: 1, filters: {{ "
                            f"company: {lead}.company_domain ? {{ websites: {{ include: [{lead}.company_domain] }} }} "
                            f": {{ names: {{ include: [{lead}.company_name || '__none__'] }} }}, "
                            f"person_seniority: {{ include: {SENIORITIES!r} }} }} }})",
                  retry=True, never_error=True)
    found = if_true(wf, "Prospeo found people?", "($json.results || []).length > 0")
    employees = http(wf, "Deepline: LinkedIn employees", "POST",
                     DEEPLINE_EXECUTE.format(tool="harvestapi_search_leads"), "deepline",
                     body_expr=f"JSON.stringify({{ payload: {{ currentCompanies: {lead}.company_linkedin_url || {lead}.company_name }} }})",
                     never_error=True, timeout_ms=120000, pos=[wf._x, 200])
    cands = code(wf, "Candidates", "expansion_candidates")
    any_cand = if_true(wf, "Any candidates?", "$json.candidates.length > 0")
    fit = wf.add("Fit (LLM)", "@n8n/n8n-nodes-langchain.chainLlm", 1.5,
                 {"promptType": "define", "text": FIT_PROMPT, "options": {}})
    model = wf.add("LLM", "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2,
                   {"model": {"__rl": True, "mode": "id", "value": "={{ $env.LLM_MODEL || 'gpt-5-mini' }}"},
                    "options": {}}, cred("openai"), pos=[wf._x - 240, 220])
    pick = code(wf, "Pick top people", "expansion_pick")
    total = _post_wf5(wf, "Post expected total",
                      "JSON.stringify({ type: 'expected_total', run_id: $json.run_id, expected_total: $json.expected_total })")
    any_people = if_true(wf, "Any people?", "$('Pick top people').first().json.expected_total > 0")
    split = wf.add("Split people", "n8n-nodes-base.code", 2,
                   {"jsCode": "return $('Pick top people').first().json.people.map((p) => ({ json: p }));"})
    email = http(wf, "Deepline: Datagma email", "POST", DEEPLINE_EXECUTE.format(tool="datagma_find_email"), "deepline",
                 body_expr=f"JSON.stringify({{ payload: {{ first_name: $json.first_name, last_name: $json.last_name, "
                           f"full_name: $json.full_name, domain: {lead}.company_domain }} }})",
                 never_error=True, timeout_ms=60000)
    people = code(wf, "Person callbacks", "expansion_people")
    post = _post_wf5(wf, "Post people", "JSON.stringify($json)")

    wf.chain(t, s, d, go)
    wf.connect(go, search, out=0)
    wf.connect(go, skip, out=1)
    wf.chain(search, found)
    wf.connect(found, cands, out=0)
    wf.connect(found, employees, out=1)
    wf.connect(employees, cands)
    wf.chain(cands, any_cand)
    wf.connect(any_cand, fit, out=0)
    wf.connect(any_cand, pick, out=1)
    wf.connect(fit, pick)
    wf.connect(model, fit, kind="ai_languageModel")
    wf.chain(pick, total, any_people)
    wf.connect(any_people, split, out=0)
    wf.chain(split, email, people, post)

    mark = sql(wf, "Mark run error", "update expansion_runs set status = 'error' where id = $1::uuid returning *",
               "[$('Decide').first().json.run.id]", pos=[wf._x, 400])
    report = call(wf, "Report error", "report_err", {
        "workflow": repr(wf.name), "step": "'Account expansion'",
        "lead_id": "$('Decide').first().json.lead.id",
        "error": "'Account expansion failed (people search or WF5 callback)'", "mark_lead": "false"}, pos=[wf._x + 240, 400])
    for node in (fit, total, post):
        for n in wf.nodes:
            if n["name"] == node:
                n["onError"] = "continueErrorOutput"
        wf.connect(node, mark, out=1)
    wf.connect(mark, report)
    return wf
