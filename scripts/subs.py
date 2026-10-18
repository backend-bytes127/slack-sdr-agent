"""Sub-workflows shared by the five main workflows."""
from expansion import expansion_start
from lib import (Workflow, call, code, cred, http, if_true, noop, slack, sql, sub_trigger)

# Base URL is env-overridable so the whole flow can run against scripts/mock_apis.py
HS = "($env.HUBSPOT_API_BASE || 'https://api.hubapi.com')"
CALL_DISPOSITIONS = ("({no_answer: '73a0d17f-1163-4015-bdd5-ec830791da20', "
                     "connected: 'f240bbac-87c9-4f6e-bf70-924b57d47db7', "
                     "wrong_number: '17b47fee-58de-441e-a44c-c6300d46f273', "
                     "left_voicemail: 'b2cf5968-551e-4856-9783-52b3da59a7d0'})")


def guard(wf, node, lead_expr, mark_lead=True):
    """Route a node's error output to the shared Report error sub-workflow."""
    for n in wf.nodes:
        if n["name"] == node:
            n["onError"] = "continueErrorOutput"
    name = "Report error"
    if not any(n["name"] == name for n in wf.nodes):
        call(wf, name, "report_err", {
            "workflow": repr(wf.name),
            "step": "$prevNode.name",
            "lead_id": lead_expr,
            "error": "JSON.stringify($json.error ?? $json).slice(0, 2000)",
            "mark_lead": "true" if mark_lead else "false",
        }, pos=[wf._x, 400])
    wf.connect(node, name, out=1)


def slack_api():
    # No error workflow: WF4 itself alerts through this sub, so failures must not loop back into WF4
    wf = Workflow("slack", "SDR · sub · Slack API", error_workflow=False)
    t = sub_trigger(wf, ["method", "payload"])
    h = http(wf, "Call Slack", "POST", "={{ ($env.SLACK_API_BASE || 'https://slack.com/api') + '/' + $json.method }}", "slack",
             body_expr="JSON.stringify($json.payload)", retry=True)
    c = code(wf, "Check ok", "slack_check")
    wf.chain(t, h, c)
    return wf


# Base URLs are env-overridable so the flow can run against scripts/mock_apis.py
DEEPLINE_EXECUTE = "={{{{ ($env.DEEPLINE_API_BASE || 'https://code.deepline.com/api/v2') + '/integrations/{tool}/execute' }}}}"
PROSPEO = "($env.PROSPEO_API_BASE || 'https://api.prospeo.io')"

RESEARCH_PROMPT = """=You are helping an SDR prepare a cold call. Use ONLY the data below. No guesses; if data is missing, say so.

Person: {{ $json.full_name }}, {{ $json.title }} at {{ $json.company_name }}
Headline: {{ $json.headline }}
Location: {{ $json.location }}
About: {{ $json.about || 'n/a' }}
Company: {{ ($json.company && ($json.company.description_ai || $json.company.description)) || 'n/a' }}
Company size / industry: {{ ($json.company && $json.company.employee_range) || 'n/a' }} / {{ ($json.company && $json.company.industry) || 'n/a' }}

Return JSON only, no markdown: {"summary": [3 short bullets on who they are and what they likely care about], "talking_points": [3 specific cold-call openers grounded only in the data above]}"""


def enrich_lead():
    """Enrich one lead. Default: Deepline LinkedIn profile + Prospeo email/mobile/company, Deepline company page
    when Prospeo has the wrong/no company, Datagma -> Hunter email waterfall, LLM research,
    posted into WF2 exactly like the old Clay callback. ENRICH_PROVIDER=clay keeps the Clay Table 1 path."""
    wf = Workflow("enrich", "SDR · sub · Enrich lead (Deepline + Prospeo, or Clay)")
    lead = "$('Mark enriching').first().json"
    t = sub_trigger(wf, ["lead_id"])
    s = sql(wf, "Mark enriching",
            "update leads set status = 'enriching' where id = $1::uuid "
            "and status in ('received', 'enriching', 'error') returning *",
            "[$json.lead_id ?? null]")
    use_clay = if_true(wf, "Use Clay?", "$env.ENRICH_PROVIDER === 'clay'")
    clay = http(wf, "Send to Clay Table 1", "POST", "={{ $env.CLAY_T1_WEBHOOK_URL }}",
                body_expr="JSON.stringify({ lead_id: $json.id, linkedin_url: $json.linkedin_url, "
                          "source: $json.source, sdr_slack_id: $json.sdr_slack_id })", retry=True, pos=[wf._x, -200])
    profile = http(wf, "Deepline: LinkedIn profile", "POST", DEEPLINE_EXECUTE.format(tool="harvestapi_get_profile"),
                   "deepline", body_expr=f"JSON.stringify({{ payload: {{ url: {lead}.linkedin_url }} }})",
                   retry=True, timeout_ms=120000)
    person = http(wf, "Prospeo: enrich person", "POST", "={{ " + PROSPEO + " + '/enrich-person' }}", "prospeo",
                  body_expr=f"JSON.stringify({{ data: {{ linkedin_url: {lead}.linkedin_url }}, "
                            f"only_verified_email: false, enrich_mobile: true }})", retry=True, never_error=True)
    merge = code(wf, "Merge profile + Prospeo", "enrich_merge")
    need_co = if_true(wf, "Need company lookup?", "$json.needs_company")
    company = http(wf, "Deepline: LinkedIn company", "POST", DEEPLINE_EXECUTE.format(tool="harvestapi_get_company"),
                   "deepline", body_expr="JSON.stringify({ payload: { url: $json.company_linkedin_url } })",
                   retry=True, never_error=True, timeout_ms=120000, pos=[wf._x, -200])
    ctx = code(wf, "Company context", "company_context")
    # Email waterfall after Prospeo: Datagma, then Hunter (both via Deepline), only when a domain is known
    need_email = if_true(wf, "Find email?", "!$json.work_email && Boolean($json.company_domain)")
    finder_body = ("JSON.stringify({{ payload: {{ first_name: {c}.first_name, last_name: {c}.last_name, "
                   "full_name: {c}.full_name, domain: {c}.company_domain }} }})").format(c="$('Company context').first().json")
    datagma = http(wf, "Deepline: Datagma email", "POST", DEEPLINE_EXECUTE.format(tool="datagma_find_email"),
                   "deepline", body_expr=finder_body, never_error=True, timeout_ms=60000, pos=[wf._x, -200])
    x = wf._x
    datagma_ok = if_true(wf, "Datagma valid?",
                         "Boolean($json.result && $json.result.data && $json.result.data.email "
                         "&& String($json.result.data.status).toLowerCase() === 'valid')", pos=[x + 240, -200])
    hunter = http(wf, "Deepline: Hunter email", "POST", DEEPLINE_EXECUTE.format(tool="hunter_email_finder"),
                  "deepline", body_expr=finder_body, never_error=True, timeout_ms=60000, pos=[x + 480, -300])
    wf._x += 720
    lead_ctx = code(wf, "Lead context", "lead_context")
    research = wf.add("Research (LLM)", "@n8n/n8n-nodes-langchain.chainLlm", 1.5,
                      {"promptType": "define", "text": RESEARCH_PROMPT, "options": {}})
    model = wf.add("LLM", "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2,
                   {"model": {"__rl": True, "mode": "id", "value": "={{ $env.LLM_MODEL || 'gpt-5-mini' }}"},
                    "options": {}}, cred("openai"), pos=[wf._x - 240, 220])
    build = code(wf, "Build enrichment payload", "enrich_payload")
    post = http(wf, "Post to WF2 (enriched)", "POST", "http://localhost:5678/webhook/sdr-enriched", "claycb",
                body_expr="JSON.stringify($json)", retry=True)

    wf.chain(t, s, use_clay)
    wf.connect(use_clay, clay, out=0)
    wf.connect(use_clay, profile, out=1)
    wf.chain(profile, person, merge, need_co)
    wf.connect(need_co, company, out=0)
    wf.connect(need_co, ctx, out=1)
    wf.connect(company, ctx)
    wf.chain(ctx, need_email)
    wf.connect(need_email, datagma, out=0)
    wf.connect(need_email, lead_ctx, out=1)
    wf.connect(datagma, datagma_ok)
    wf.connect(datagma_ok, lead_ctx, out=0)
    wf.connect(datagma_ok, hunter, out=1)
    wf.connect(hunter, lead_ctx)
    wf.chain(lead_ctx, research, build, post)
    wf.connect(model, research, kind="ai_languageModel")
    for n in (clay, profile, post):
        guard(wf, n, f"{lead}.id")
    return wf


def hubspot_sync():
    wf = Workflow("hs_sync", "SDR · sub · HubSpot company + contact sync")
    lead = "$('Load lead').first().json"
    t = sub_trigger(wf, ["lead_id"])
    load = sql(wf, "Load lead",
               "select l.*, m.hubspot_owner_id from leads l left join sdr_owner_map m "
               "on m.slack_user_id = l.sdr_slack_id where l.id = $1::uuid",
               "[$json.lead_id ?? null]")
    search_co = http(wf, "Search company", "POST", "={{ " + HS + " + '/crm/v3/objects/companies/search' }}", "hubspot",
                     body_expr="JSON.stringify({ filterGroups: [{ filters: [ $json.company_domain "
                               "? { propertyName: 'domain', operator: 'EQ', value: $json.company_domain } "
                               ": { propertyName: 'name', operator: 'EQ', value: $json.company_name || '__none__' } ] }], "
                               "properties: ['name', 'domain'], limit: 1 })", retry=True)
    found = if_true(wf, "Company found?", "($json.results || []).length > 0")
    has_co = if_true(wf, "Has company data?", f"Boolean({lead}.company_name || {lead}.company_domain)")
    create_co = http(wf, "Create company", "POST", "={{ " + HS + " + '/crm/v3/objects/companies' }}", "hubspot",
                     body_expr=f"JSON.stringify({{ properties: Object.fromEntries(Object.entries({{ "
                               f"name: {lead}.company_name || {lead}.company_domain, domain: {lead}.company_domain, "
                               f"description: {lead}.company_description, linkedin_company_page: {lead}.company_linkedin_url "
                               f"}}).filter(([k, v]) => v)) }})", retry=True)
    co_id = wf.add("Company ID", "n8n-nodes-base.code", 2, {"jsCode": (
        "let id = null;\n"
        "if ($('Search company').isExecuted) id = (($('Search company').first().json.results || [])[0] || {}).id || null;\n"
        "if (!id && $('Create company').isExecuted) id = $('Create company').first().json.id || null;\n"
        "return [{ json: { company_id: id } }];")})
    search_ct = http(wf, "Search contact", "POST", "={{ " + HS + " + '/crm/v3/objects/contacts/search' }}", "hubspot",
                     body_expr=f"JSON.stringify({{ filterGroups: [ "
                               f"...({lead}.work_email ? [{{ filters: [{{ propertyName: 'email', operator: 'EQ', value: {lead}.work_email }}] }}] : []), "
                               f"{{ filters: [{{ propertyName: 'linkedin_url', operator: 'EQ', value: {lead}.linkedin_url }}] }} ], "
                               f"properties: ['email', 'hubspot_owner_id'], limit: 1 }})", retry=True)
    plan = code(wf, "Plan contact upsert", "hubspot_contact")
    exists = if_true(wf, "Contact exists?", "$json.exists")
    update_ct = http(wf, "Update contact", "PATCH", "={{ " + HS + " + '/crm/v3/objects/contacts/' + $json.contact_id }}",
                     "hubspot", body_expr="JSON.stringify({ properties: $json.properties })", retry=True)
    create_ct = http(wf, "Create contact", "POST", "={{ " + HS + " + '/crm/v3/objects/contacts' }}", "hubspot",
                     body_expr="JSON.stringify({ properties: $json.properties })", retry=True)
    ct_id = wf.add("Contact ID", "n8n-nodes-base.code", 2, {"jsCode": (
        "return [{ json: { contact_id: $json.id, company_id: $('Company ID').first().json.company_id, "
        "owner_conflict: $('Plan contact upsert').first().json.owner_conflict } }];")})
    has_assoc = if_true(wf, "Associate company?", "Boolean($json.company_id)")
    assoc = http(wf, "Associate contact to company", "PUT",
                 "={{ " + HS + " + '/crm/v4/objects/contact/' + $json.contact_id + '/associations/default/company/' + $json.company_id }}",
                 "hubspot", retry=True)
    note = http(wf, "Add research note", "POST", "={{ " + HS + " + '/crm/v3/objects/notes' }}", "hubspot",
                body_expr=f"JSON.stringify({{ properties: {{ hs_timestamp: new Date().toISOString(), "
                          f"hs_note_body: '<b>SDR Agent research</b><br>' + String({lead}.research_summary || 'No research').replace(/\\n/g, '<br>') "
                          f"+ '<br><br><b>Talking points</b><br>' + String({lead}.talking_points || '-').replace(/\\n/g, '<br>') }}, "
                          f"associations: [{{ to: {{ id: $('Contact ID').first().json.contact_id }}, "
                          f"types: [{{ associationCategory: 'HUBSPOT_DEFINED', associationTypeId: 202 }}] }}] }})", retry=True)
    save = sql(wf, "Save HubSpot IDs",
               "update leads set hubspot_contact_id = $2, hubspot_company_id = $3, status = 'in_crm' "
               "where id = $1::uuid returning *",
               f"[{lead}.id, $('Contact ID').first().json.contact_id ?? null, $('Contact ID').first().json.company_id ?? null]")
    owner_warn = if_true(wf, "Owner conflict?", "$('Contact ID').first().json.owner_conflict === true", pos=[wf._x, 300])
    warn = slack(wf, "Warn owner conflict", "'chat.postMessage'",
                 f"({{ channel: {lead}.slack_channel_id, thread_ts: {lead}.slack_thread_ts, "
                 f"text: ':warning: This contact already has a different HubSpot owner. Owner was not changed; check with your manager.' }})")

    wf.chain(t, load, search_co, found)
    wf.connect(found, co_id, out=0)
    wf.connect(found, has_co, out=1)
    wf.connect(has_co, create_co, out=0)
    wf.connect(has_co, co_id, out=1)
    wf.connect(create_co, co_id)
    wf.chain(co_id, search_ct, plan, exists)
    wf.connect(exists, update_ct, out=0)
    wf.connect(exists, create_ct, out=1)
    wf.connect(update_ct, ct_id)
    wf.connect(create_ct, ct_id)
    wf.connect(ct_id, owner_warn)
    wf.connect(owner_warn, warn, out=0)
    wf.connect(ct_id, has_assoc)
    wf.connect(has_assoc, assoc, out=0)
    wf.connect(has_assoc, note, out=1)
    wf.connect(assoc, note)
    wf.connect(note, save)
    for n in (search_co, create_co, search_ct, update_ct, create_ct, assoc, note):
        guard(wf, n, f"{lead}.id")
    return wf


def hubspot_call():
    wf = Workflow("hs_call", "SDR · sub · HubSpot log call")
    inp = "$('Called by parent').first().json"
    t = sub_trigger(wf, ["lead_id", "disposition", "title", "body"])
    load = sql(wf, "Load lead",
               "select l.id, l.hubspot_contact_id, m.hubspot_owner_id from leads l left join sdr_owner_map m "
               "on m.slack_user_id = l.sdr_slack_id where l.id = $1::uuid",
               "[$json.lead_id ?? null]")
    has = if_true(wf, "In HubSpot?", "Boolean($json.hubspot_contact_id)")
    h = http(wf, "Log call", "POST", "={{ " + HS + " + '/crm/v3/objects/calls' }}", "hubspot",
             body_expr=f"JSON.stringify({{ properties: Object.fromEntries(Object.entries({{ "
                       f"hs_timestamp: new Date().toISOString(), hs_call_title: {inp}.title, "
                       f"hs_call_body: {inp}.body, hs_call_status: 'COMPLETED', hs_call_direction: 'OUTBOUND', "
                       f"hs_call_disposition: {CALL_DISPOSITIONS}[{inp}.disposition], hubspot_owner_id: $json.hubspot_owner_id "
                       f"}}).filter(([k, v]) => v)), associations: [{{ to: {{ id: $json.hubspot_contact_id }}, "
                       f"types: [{{ associationCategory: 'HUBSPOT_DEFINED', associationTypeId: 194 }}] }}] }})", retry=True)
    wf.chain(t, load, has, h)
    guard(wf, h, "$('Load lead').first().json.id", mark_lead=False)
    return wf


def hubspot_note():
    wf = Workflow("hs_note", "SDR · sub · HubSpot note")
    t = sub_trigger(wf, ["lead_id", "body"])
    load = sql(wf, "Load lead", "select id, hubspot_contact_id from leads where id = $1::uuid",
               "[$json.lead_id ?? null]")
    has = if_true(wf, "In HubSpot?", "Boolean($json.hubspot_contact_id)")
    h = http(wf, "Add note", "POST", "={{ " + HS + " + '/crm/v3/objects/notes' }}", "hubspot",
             body_expr="JSON.stringify({ properties: { hs_timestamp: new Date().toISOString(), "
                       "hs_note_body: String($('Called by parent').first().json.body || '').replace(/\\n/g, '<br>') }, "
                       "associations: [{ to: { id: $json.hubspot_contact_id }, "
                       "types: [{ associationCategory: 'HUBSPOT_DEFINED', associationTypeId: 202 }] }] })", retry=True)
    wf.chain(t, load, has, h)
    guard(wf, h, "$('Load lead').first().json.id", mark_lead=False)
    return wf


def lead_card():
    wf = Workflow("lead_card", "SDR · sub · Post or update lead card")
    t = sub_trigger(wf, ["lead_id", "mode", "note"])
    load = sql(wf, "Load lead", "select * from leads where id = $1::uuid", "[$json.lead_id ?? null]")
    build = code(wf, "Build lead card", "lead_card")
    post = slack(wf, "Send card", "$json.method", "$json.payload")
    save = sql(wf, "Save card ts",
               "update leads set card_message_ts = coalesce($2, card_message_ts) where id = $1::uuid returning *",
               "[$('Build lead card').first().json.lead_id, $json.ts ?? null]")
    wf.chain(t, load, build, post, save)
    return wf


EXPANSION_CARD_SQL = """
select r.*,
  coalesce((select json_agg(p order by p.fit_score desc nulls last, p.created_at)
            from (select id, full_name, title, fit_score, fit_reason, work_email, email_status,
                         linkedin_url, status, created_at
                  from leads where expansion_run_id = r.id) p), '[]'::json) as people
from expansion_runs r where r.id = $1::uuid
""".strip()


def expansion_card():
    wf = Workflow("exp_card", "SDR · sub · Post or update expansion card")
    t = sub_trigger(wf, ["run_id"])
    load = sql(wf, "Load run", EXPANSION_CARD_SQL, "[$json.run_id ?? null]")
    build = code(wf, "Build expansion card", "expansion_card")
    post = slack(wf, "Send card", "$json.method", "$json.payload")
    save = sql(wf, "Save card ts",
               "update expansion_runs set slack_message_ts = coalesce(slack_message_ts, $2), "
               "status = case when $3::int = 0 then 'empty' else 'posted' end where id = $1::uuid returning *",
               "[$('Build expansion card').first().json.run_id, $json.ts ?? null, "
               "$('Build expansion card').first().json.people_count]")
    wf.chain(t, load, build, post, save)
    return wf


DRAFT_PROMPT = """=Write a LinkedIn message from {{ $('Called by parent').first().json.sdr_name || 'the SDR' }} to {{ $json.first_name || $json.full_name }}, {{ $json.title }} at {{ $json.company_name }}. They just spoke on the phone.

Call notes: {{ $('Called by parent').first().json.notes || '(no notes)' }}
Goal of this message: {{ String($('Called by parent').first().json.goal || 'soft_follow_up').replace(/_/g, ' ') }}

Background (use only if it supports something said on the call):
{{ $json.research_summary || 'none' }}

Rules:
- Under 300 characters, so it also fits a connection-request note
- Reference one specific thing they said on the call
- One clear next step, no hard pitch
- Plain, human tone; no emojis, no "I hope this finds you well"
- Never invent facts that are not in the notes
{{ $('Called by parent').first().json.previous_draft ? '- Write a clearly different message from this previous draft: ' + $('Called by parent').first().json.previous_draft : '' }}
Return only the message text."""


def draft_message():
    wf = Workflow("draft", "SDR · sub · AI draft LinkedIn message")
    t = sub_trigger(wf, ["lead_id", "notes", "goal", "sdr_name", "previous_draft"])
    load = sql(wf, "Load lead", "select * from leads where id = $1::uuid", "[$json.lead_id ?? null]")
    chain = wf.add("Draft message", "@n8n/n8n-nodes-langchain.chainLlm", 1.5,
                   {"promptType": "define", "text": DRAFT_PROMPT, "options": {}})
    model = wf.add("LLM", "@n8n/n8n-nodes-langchain.lmChatOpenAi", 1.2,
                   {"model": {"__rl": True, "mode": "id", "value": "={{ $env.LLM_MODEL || 'gpt-5-mini' }}"},
                    "options": {}}, cred("openai"), pos=[wf._x - 240, 220])
    clean = code(wf, "Clean draft", "draft_clean")
    wf.chain(t, load, chain, clean)
    wf.connect(model, chain, kind="ai_languageModel")
    return wf


REPORT_SQL = """
with e as (
  insert into workflow_errors (workflow, step, lead_id, error, payload)
  values ($1, $2, nullif($3, '')::uuid, $4, $5::jsonb) returning id
),
u as (
  update leads set status = 'error'
  where id = nullif($3, '')::uuid and $6::boolean and status not in ('do_not_contact')
  returning id
)
select (select id from e) as error_id, (select count(*) from u) as marked,
       l.id, l.slack_channel_id, l.slack_thread_ts
from (select 1) d left join leads l on l.id = nullif($3, '')::uuid
""".strip()


def report_error():
    wf = Workflow("report_err", "SDR · sub · Report error", error_workflow=False)
    t = sub_trigger(wf, ["workflow", "step", "lead_id", "error", "mark_lead"])
    s = sql(wf, "Log error", REPORT_SQL,
            "[$json.workflow ?? null, $json.step ?? null, String($json.lead_id ?? ''), "
            "String($json.error ?? ''), JSON.stringify({ step: $json.step }), String($json.mark_lead !== false && $json.mark_lead !== 'false')]")
    build = code(wf, "Build alert", "error_alert")
    post = slack(wf, "Alert in thread", "'chat.postMessage'", "$json.payload")
    done = wf.add("Return failed", "n8n-nodes-base.code", 2,
                  {"jsCode": "return [{ json: { ok: false } }];"})
    wf.chain(t, s, build, post, done)
    return wf


def all_subs():
    return [slack_api(), enrich_lead(), hubspot_sync(), hubspot_call(), hubspot_note(), lead_card(),
            expansion_start(), expansion_card(), draft_message(), report_error()]
